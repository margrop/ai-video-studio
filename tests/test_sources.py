import asyncio

import pytest

from packages.workflow import SourceError, fetch_article, fetch_feed, parse_article_html, parse_feed


def test_parse_rss_and_atom_items_with_safe_limits() -> None:
    rss = """
    <rss><channel>
      <item><title>First item</title><description><![CDATA[An <b>article</b>.]]></description><link>https://example.test/1</link></item>
      <item><title>Second item</title><description>Second body</description></item>
    </channel></rss>
    """
    atom = """
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Atom item</title><summary>Atom body</summary>
        <link href="https://example.test/a" />
      </entry>
    </feed>
    """

    rss_items = parse_feed(rss)
    atom_items = parse_feed(atom)

    assert rss_items[0].title == "First item"
    assert rss_items[0].url == "https://example.test/1"
    assert atom_items[0].url == "https://example.test/a"


def test_feed_url_validation_happens_before_network() -> None:
    with pytest.raises(SourceError, match="http or https"):
        asyncio.run(fetch_feed("file:///tmp/feed.xml"))


def test_parse_article_html_removes_non_content_tags() -> None:
    article = parse_article_html(
        """
        <html><head><title>Page title</title><script>ignore me</script></head>
        <body><nav>Navigation</nav><h1>Readable article</h1>
        <article><p>This is the first paragraph with useful content.</p>
        <p>And this is a second paragraph for the video planner.</p></article>
        <style>ignore style</style></body></html>
        """,
        url="https://example.test/article",
    )
    assert article.title == "Readable article"
    assert "useful content" in article.body
    assert "ignore me" not in article.body
    assert article.url == "https://example.test/article"


def test_article_fetch_requires_an_explicit_host_allowlist() -> None:
    with pytest.raises(SourceError, match="AIVS_SOURCE_ALLOWED_HOSTS"):
        asyncio.run(fetch_article("https://example.test/article"))
