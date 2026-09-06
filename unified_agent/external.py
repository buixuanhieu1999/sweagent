"""Deferred network capabilities with normalized, bounded results."""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


def _download(url: str, limit: int = 1_000_000) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must be an absolute http(s) URL")
    request = urllib.request.Request(url, headers={"User-Agent": "UnifiedAgent/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Response exceeds 1 MB")
        return data.decode("utf-8", errors="replace"), response.url


def search(query: str, limit: int = 5) -> dict:
    if not query.strip() or len(query) > 500:
        raise ValueError("Search query must be 1 to 500 characters")
    encoded = urllib.parse.urlencode({"q": query})
    page, _ = _download("https://html.duckduckgo.com/html/?" + encoded)
    rows = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'
        r".*?(?:result__snippet[^>]*>(?P<snippet>.*?)</(?:a|div))?",
        re.S,
    )
    for match in pattern.finditer(page):
        url = html.unescape(match.group("url"))
        if url.startswith("/l/?"):
            target = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("uddg")
            url = target[0] if target else url
        text = _TextExtractor()
        text.feed(match.group("title"))
        title = text.text()
        text = _TextExtractor()
        text.feed(match.group("snippet") or "")
        rows.append({"title": title, "url": url, "snippet": text.text()[:500]})
        if len(rows) >= limit:
            break
    return {"query": query, "results": rows}


def fetch(url: str, max_chars: int = 16_000) -> dict:
    if max_chars < 1 or max_chars > 100_000:
        raise ValueError("max_chars must be 1 to 100,000")
    body, final_url = _download(url)
    parser = _TextExtractor()
    parser.feed(body)
    return {"url": final_url, "text": parser.text()[:max_chars]}
