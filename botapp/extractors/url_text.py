from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from readability import Document


_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_MIN_MEANINGFUL_ARTICLE_LEN = 500
_NOISE_BLOCK_RE = re.compile(
    r"(cookie|consent|banner|promo|advert|ads|share|subscribe|social|"
    r"footer|header|menu|nav|breadcrumb|related|repost|recommend|"
    r"подпис|реклам|cookie|коммент|меню|хлебн)",
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


def _clean_noise(soup: BeautifulSoup) -> None:
    for noise in soup.select(
        "script, style, noscript, nav, footer, aside, form, iframe, header, svg, button"
    ):
        noise.decompose()

    for node in list(soup.find_all(True)):
        if node.attrs is None:
            continue
        attrs_text = " ".join(
            [
                str(node.get("id", "")),
                " ".join(node.get("class", [])),
                str(node.get("role", "")),
            ]
        )
        if _NOISE_BLOCK_RE.search(attrs_text):
            node.decompose()


def _node_score(node: Tag) -> tuple[float, str]:
    paragraphs = [_normalize_text(p.get_text(" ", strip=True)) for p in node.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) >= 20]
    list_items = [_normalize_text(li.get_text(" ", strip=True)) for li in node.find_all("li")]
    list_items = [li for li in list_items if len(li) >= 20]

    headings = [_normalize_text(h.get_text(" ", strip=True)) for h in node.find_all(["h1", "h2", "h3"])]
    headings = [h for h in headings if len(h) >= 8]

    chunks = headings + paragraphs + list_items
    if not chunks:
        text = _normalize_text(node.get_text(" ", strip=True))
        if len(text) < 200:
            return -1.0, ""
        chunks = [text]

    text = _normalize_text(" ".join(chunks))
    link_text = _normalize_text(" ".join(a.get_text(" ", strip=True) for a in node.find_all("a")))
    link_density = len(link_text) / max(len(text), 1)
    boilerplate_hits = len(_NOISE_BLOCK_RE.findall(text))

    score = (
        len(text)
        + (120 * len(paragraphs))
        + (35 * len(list_items))
        - (900 * link_density)
        - (180 * boilerplate_hits)
    )

    if len(paragraphs) < 2 and len(text) < 700:
        score -= 250

    return score, text


def _best_scored_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    seen: set[int] = set()
    best_text = ""
    best_score = float("-inf")

    for selector in selectors:
        for node in soup.select(selector):
            node_id = id(node)
            if node_id in seen:
                continue
            seen.add(node_id)

            score, text = _node_score(node)
            if score > best_score and text:
                best_score = score
                best_text = text

    return best_text


def _extract_from_dom(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    _clean_noise(soup)

    primary_selectors = [
        "article",
        "main",
        "[role='main']",
        "[itemprop='articleBody']",
    ]
    broad_selectors = [
        "[class*='article']",
        "[class*='content']",
        "[class*='post']",
        "[class*='entry']",
        "section",
        "div",
    ]

    best_text = _best_scored_text(soup, primary_selectors)
    if len(best_text) >= _MIN_MEANINGFUL_ARTICLE_LEN:
        return best_text

    fallback_text = _best_scored_text(soup, broad_selectors)
    if len(fallback_text) > len(best_text):
        best_text = fallback_text

    if best_text:
        return best_text

    body = soup.body or soup
    return _normalize_text(body.get_text(" ", strip=True))


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

    candidates = [
        _extract_from_dom(html),
        _extract_from_dom(main_html),
        _extract_from_json_ld(html),
    ]
    text = max(candidates, key=len, default="")

    if not text:
        text = _normalize_text(BeautifulSoup(main_html, "html.parser").get_text(" ", strip=True))

    if len(text) < _MIN_MEANINGFUL_ARTICLE_LEN:
        json_ld_text = _extract_from_json_ld(html)
        if len(json_ld_text) > len(text):
            text = json_ld_text

    if title and title not in text:
        text = f"{title}. {text}"

    return _normalize_text(text)
