from __future__ import annotations

from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfReader


async def extract_pdf_text_from_url(url: str, timeout_seconds: int = 20) -> str:
    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

    return extract_pdf_text_from_bytes(response.content)



def extract_pdf_text_from_file(path: Path) -> str:
    with path.open("rb") as file:
        reader = PdfReader(file)
        return _extract_from_reader(reader)



def extract_pdf_text_from_bytes(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    return _extract_from_reader(reader)



def _extract_from_reader(reader: PdfReader) -> str:
    chunks = []
    for page in reader.pages:
        extracted = page.extract_text() or ""
        if extracted.strip():
            chunks.append(extracted)
    return "\n".join(chunks).strip()
