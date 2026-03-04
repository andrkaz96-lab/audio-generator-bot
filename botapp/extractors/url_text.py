from __future__ import annotations

import re
import json
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from readability import Document


_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_MIN_MEANINGFUL_ARTICLE_LEN = 500


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_from_json_ld(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            body = obj.get("articleBody")
            if isinstance(body, str):
                candidates.append(_normalize_text(body))
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            walk(json.loads(raw))
        except json.JSONDecodeError:
            continue

    return max(candidates, key=len, default="")


def _extract_from_dom(main_html: str) -> str:
    soup = BeautifulSoup(main_html, "html.parser")
    for noise in soup.select("script, style, noscript, nav, footer, aside, form, iframe"):
        noise.decompose()

    selectors = [
        "article",
        "[itemprop='articleBody']",
        ".article__body",
        ".article-body",
        ".post-content",
        ".entry-content",
    ]

    chunks: list[str] = []
    for selector in selectors:
        for node in soup.select(selector):
            chunks.append(_normalize_text(node.get_text(" ", strip=True)))

    # Fallback to full content if no well-known container matched.
    if not chunks:
        chunks.append(_normalize_text(soup.get_text(" ", strip=True)))

    return max(chunks, key=len, default="")



def extract_url(text: str) -> str | None:
    if not text:
        return None
    match = _URL_RE.search(text)
    if not match:
        return None
    candidate = match.group(0).rstrip(").,;:!?\"")
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate
    return None


async def fetch_article_text(url: str, timeout_seconds: int = 20) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru,en;q=0.9",
    }

    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()

    html = response.text
    doc = Document(html)
    title = doc.title() or ""
    main_html = doc.summary(html_partial=True)

    text = _extract_from_dom(main_html)
    if len(text) < _MIN_MEANINGFUL_ARTICLE_LEN:
        json_ld_text = _extract_from_json_ld(html)
        if len(json_ld_text) > len(text):
            text = json_ld_text

    if title and title not in text:
        text = f"{title}. {text}"

    return _normalize_text(text)
