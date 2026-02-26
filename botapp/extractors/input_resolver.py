from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from botapp.extractors.pdf_text import extract_pdf_text_from_file, extract_pdf_text_from_url
from botapp.extractors.url_text import extract_url, fetch_article_text
from botapp.utils.text import normalize_text


@dataclass(frozen=True)
class ResolvedInput:
    source: str
    text: str


async def resolve_input_text(
    raw_text: str | None,
    pdf_local_path: Path | None,
    timeout_seconds: int,
) -> ResolvedInput:
    if pdf_local_path is not None:
        text = extract_pdf_text_from_file(pdf_local_path)
        return ResolvedInput(source="pdf", text=normalize_text(text))

    cleaned = normalize_text(raw_text or "")
    if not cleaned:
        return ResolvedInput(source="empty", text="")

    maybe_url = extract_url(cleaned)
    if maybe_url:
        if maybe_url.lower().endswith(".pdf"):
            text = await extract_pdf_text_from_url(maybe_url, timeout_seconds=timeout_seconds)
            return ResolvedInput(source="pdf_url", text=normalize_text(text))

        text = await fetch_article_text(maybe_url, timeout_seconds=timeout_seconds)
        return ResolvedInput(source="url", text=normalize_text(text))

    return ResolvedInput(source="text", text=cleaned)
