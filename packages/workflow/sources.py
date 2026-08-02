"""Safe Markdown and RSS/Atom article sources for content workflows."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
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
