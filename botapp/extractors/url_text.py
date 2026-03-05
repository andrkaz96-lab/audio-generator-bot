from __future__ import annotations

import re
import json
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup
from readability import Document


_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_MIN_MEANINGFUL_ARTICLE_LEN = 500
_BOILERPLATE_RE = re.compile(
    r"(подписк|cookies|политик[аеи]|copyright|все права защищены|"
    r"поделиться|комментар|реклам|подвал|навигац)",
    re.IGNORECASE,
)


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




def _normalize_embedded_text(value: str) -> str:
    cleaned = _normalize_text(value)
    if "<" in cleaned and ">" in cleaned:
        cleaned = _normalize_text(BeautifulSoup(cleaned, "html.parser").get_text(" ", strip=True))
    return cleaned


def _looks_like_article_text(value: str) -> bool:
    if len(value) < 140:
        return False
    if value.count(" ") < 20:
        return False
    return True


def _extract_from_embedded_data(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []

    def add_candidate(raw: str) -> None:
        normalized = _normalize_embedded_text(raw)
        if _looks_like_article_text(normalized):
            candidates.append(normalized)

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str) and any(
                    token in key.lower()
                    for token in ("article", "content", "body", "text", "html", "paragraph", "rendered")
                ):
                    add_candidate(value)
                walk(value)
        elif isinstance(obj, list):
            joined_text_chunks: list[str] = []
            for item in obj:
                if isinstance(item, str):
                    normalized = _normalize_embedded_text(item)
                    if len(normalized) >= 60:
                        joined_text_chunks.append(normalized)
                elif isinstance(item, dict):
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        normalized = _normalize_embedded_text(text_value)
                        if len(normalized) >= 60:
                            joined_text_chunks.append(normalized)
                walk(item)
            if len(joined_text_chunks) >= 2:
                add_candidate(" ".join(joined_text_chunks))
        elif isinstance(obj, str):
            add_candidate(obj)

    for script in soup.find_all("script"):
        script_id = (script.get("id") or "").lower()
        script_type = (script.get("type") or "").lower()
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        is_json_like = "json" in script_type or script_id in {"__next_data__", "__nuxt"}
        if not is_json_like:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        walk(payload)

    return max(candidates, key=len, default="")

def _extract_from_dom(main_html: str) -> str:
    soup = BeautifulSoup(main_html, "html.parser")
    for noise in soup.select("script, style, noscript, nav, footer, aside, form, iframe, header"):
        noise.decompose()

    for noise in soup.select(
        "[class*='nav'], [class*='menu'], [class*='footer'], [class*='header'], "
        "[class*='share'], [class*='comment'], [class*='cookie'], [class*='banner'], "
        "[id*='nav'], [id*='menu'], [id*='footer'], [id*='header'], [id*='share'], [id*='comment']"
    ):
        noise.decompose()

    selectors = [
        "article",
        "main",
        "[role='main']",
        "[itemprop='articleBody']",
        ".article__body",
        ".article-body",
        ".article-content",
        ".post-content",
        ".entry-content",
        ".content",
        ".post",
    ]

    def node_to_text(node: BeautifulSoup) -> str:
        paragraphs = [
            _normalize_text(p.get_text(" ", strip=True))
            for p in node.select("p, h1, h2, h3, li")
            if p.get_text(strip=True)
        ]
        if paragraphs:
            return _normalize_text(" ".join(paragraphs))
        return _normalize_text(node.get_text(" ", strip=True))

    chunks: list[str] = []
    for selector in selectors:
        for node in soup.select(selector):
            chunk = node_to_text(node)
            if chunk:
                chunks.append(chunk)

    parent_scores: dict[object, int] = {}
    for p in soup.select("p"):
        p_text = _normalize_text(p.get_text(" ", strip=True))
        if len(p_text) < 60:
            continue
        parent = p.parent
        if parent is None:
            continue
        parent_scores[parent] = parent_scores.get(parent, 0) + len(p_text)

    if parent_scores:
        best_parent = max(parent_scores.items(), key=lambda item: item[1])[0]
        parent_chunk = node_to_text(best_parent)
        if parent_chunk:
            chunks.append(parent_chunk)

    # Fallback to body content if no well-known container matched.
    if not chunks:
        body = soup.body or soup
        chunks.append(_normalize_text(body.get_text(" ", strip=True)))

    def score(chunk: str) -> float:
        penalty = 0.5 if _BOILERPLATE_RE.search(chunk) else 1.0
        return len(chunk) * penalty

    return max(chunks, key=score, default="")



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

    summary_text = _extract_from_dom(main_html)
    full_dom_text = _extract_from_dom(html)
    json_ld_text = _extract_from_json_ld(html)
    embedded_data_text = _extract_from_embedded_data(html)

    candidates = [summary_text, full_dom_text, json_ld_text, embedded_data_text]
    text = max(candidates, key=len, default="")

    # If extractor returned only a tiny block, keep readability result as backup.
    if len(text) < _MIN_MEANINGFUL_ARTICLE_LEN and len(summary_text) > len(text):
        text = summary_text

    if title and title not in text:
        text = f"{title}. {text}"

    return _normalize_text(text)
