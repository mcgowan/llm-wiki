"""Web research primitives: search the internet, download pages, extract content."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import trafilatura
from ddgs import DDGS

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 llm-wiki/0.1"
)


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


@dataclass
class Extracted:
    url: str
    title: str
    author: str | None
    date: str | None  # source's own last-modified/publication date, YYYY-MM-DD
    markdown: str


def search(query: str, max_results: int = 10) -> list[SearchHit]:
    hits: list[SearchHit] = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            url = r.get("href") or r.get("url") or ""
            if not url:
                continue
            hits.append(SearchHit(title=r.get("title", url), url=url, snippet=r.get("body", "")))
    return hits


def download(url: str, timeout: float = 30.0) -> str:
    """Fetch raw HTML for a URL."""
    resp = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.text


def extract(html: str, url: str) -> Extracted:
    """Extract the main content of a page as markdown, plus source metadata."""
    markdown = trafilatura.extract(
        html, url=url, output_format="markdown", include_links=True, include_tables=True
    )
    if not markdown:
        raise ValueError(f"no extractable content at {url}")
    meta = trafilatura.extract_metadata(html, default_url=url)
    title = (meta.title if meta and meta.title else None) or url
    return Extracted(
        url=url,
        title=title,
        author=(meta.author if meta else None) or None,
        date=(meta.date if meta else None) or None,
        markdown=markdown,
    )
