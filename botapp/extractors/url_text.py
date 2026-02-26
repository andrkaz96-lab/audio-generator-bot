from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from readability import Document


_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)



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
    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

    html = response.text
    doc = Document(html)
    title = doc.title() or ""
    main_html = doc.summary(html_partial=True)

    soup = BeautifulSoup(main_html, "html.parser")
    text = soup.get_text(" ", strip=True)

    if title and title not in text:
        text = f"{title}. {text}"

    return text.strip()
