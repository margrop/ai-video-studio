"""Safe Markdown and RSS/Atom article sources for content workflows."""

from __future__ import annotations

import html
import ipaddress
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx


class SourceError(ValueError):
    """A source could not be fetched or parsed within the workflow limits."""


@dataclass(frozen=True)
class ArticleSource:
    title: str
    body: str
    url: str = ""


class _ArticleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.body_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._in_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "noscript", "template", "svg"}:
            self._skip_depth += 1
        elif normalized == "title" and self._skip_depth == 0:
            self._in_title = True
        elif normalized in {"h1", "h2"} and self._skip_depth == 0:
            self._in_heading = True

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "noscript", "template", "svg"}:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif normalized == "title":
            self._in_title = False
        elif normalized in {"h1", "h2"}:
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = re.sub(r"\s+", " ", html.unescape(data)).strip()
        if not value:
            return
        self.body_parts.append(value)
        if self._in_title:
            self.title_parts.append(value)
        if self._in_heading:
            self.heading_parts.append(value)


def from_markdown(path: Path) -> ArticleSource:
    if not path.is_file():
        raise SourceError(f"source file not found: {path}")
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SourceError("source file could not be read") from exc
    if len(content) > 30_000:
        raise SourceError("source file exceeds 30000 characters")
    title = path.stem.replace("-", " ").replace("_", " ").strip() or "Untitled article"
    first_line, _, remainder = content.strip().partition("\n")
    if first_line.lstrip().startswith("#"):
        title = first_line.lstrip("# ").strip() or title
        content = remainder
    return ArticleSource(title=title[:200], body=content[:30_000])


def _validate_source_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise SourceError("article URL must use http or https without embedded credentials")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise SourceError("article URL must use a public host")
    allowed = {
        item.strip().lower().rstrip(".")
        for item in os.getenv("AIVS_SOURCE_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    }
    if not allowed:
        raise SourceError("remote article sources require AIVS_SOURCE_ALLOWED_HOSTS")
    if not any(host == item or host.endswith(f".{item}") for item in allowed):
        raise SourceError("article host is not in AIVS_SOURCE_ALLOWED_HOSTS")
    return url


def parse_article_html(html_text: str, *, url: str = "") -> ArticleSource:
    if len(html_text.encode("utf-8")) > 2_000_000:
        raise SourceError("article exceeds 2 MB")
    parser = _ArticleHTMLParser()
    try:
        parser.feed(html_text)
        parser.close()
    except (ValueError, RuntimeError) as exc:
        raise SourceError("article HTML could not be parsed") from exc
    title = " ".join(parser.heading_parts or parser.title_parts).strip() or "Untitled article"
    body = " ".join(parser.body_parts).strip()
    if len(body) < 20:
        raise SourceError("article contained too little readable text")
    return ArticleSource(title=title[:200], body=body[:30_000], url=url[:2000])


async def fetch_article(url: str, *, timeout_seconds: float = 15.0) -> ArticleSource:
    """Fetch an allowlisted public article for an Article → Video job."""

    safe_url = _validate_source_url(url)
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            response = await client.get(
                safe_url,
                headers={"Accept": "text/html, text/plain, text/markdown"},
            )
            response.raise_for_status()
            final_url = str(response.url)
            _validate_source_url(final_url)
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not any(
                value in content_type for value in ("text/html", "text/plain", "text/markdown")
            ):
                raise SourceError("article response must be text or HTML")
            content = response.text
    except SourceError:
        raise
    except httpx.TimeoutException as exc:
        raise SourceError("article request timed out") from exc
    except httpx.HTTPError as exc:
        raise SourceError("article request failed") from exc
    return parse_article_html(content, url=final_url)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, name: str) -> str:
    for child in element.iter():
        if child is element or _local_name(child.tag) != name:
            continue
        value = "".join(child.itertext()).strip()
        if value:
            return html.unescape(re.sub(r"\s+", " ", value))
    return ""


def parse_feed(xml_text: str, *, max_items: int = 20) -> list[ArticleSource]:
    if len(xml_text.encode("utf-8")) > 1_000_000:
        raise SourceError("feed exceeds 1 MB")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError("feed XML could not be parsed") from exc

    entries = [element for element in root.iter() if _local_name(element.tag) in {"item", "entry"}]
    articles: list[ArticleSource] = []
    for entry in entries[:max_items]:
        title = _child_text(entry, "title") or "Untitled feed item"
        body = (
            _child_text(entry, "description")
            or _child_text(entry, "summary")
            or _child_text(entry, "content")
        )
        link = _child_text(entry, "link")
        if not link:
            for child in entry:
                if _local_name(child.tag) == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        articles.append(ArticleSource(title=title[:200], body=body[:30_000], url=link[:2000]))
    if not articles:
        raise SourceError("feed contained no RSS or Atom entries")
    return articles


async def fetch_feed(url: str, *, timeout_seconds: float = 15.0) -> list[ArticleSource]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SourceError("feed URL must use http or https")
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={"Accept": "application/rss+xml, application/atom+xml, text/xml"},
            )
            response.raise_for_status()
            content = response.text
    except httpx.TimeoutException as exc:
        raise SourceError("feed request timed out") from exc
    except httpx.HTTPError as exc:
        raise SourceError("feed request failed") from exc
    return parse_feed(content)
