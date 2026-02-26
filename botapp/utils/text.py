import re
from typing import List


_WHITESPACE_RE = re.compile(r"\s+")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?…])\s+")



def normalize_text(value: str) -> str:
    normalized = _WHITESPACE_RE.sub(" ", value or "").strip()
    return normalized



def split_text_into_chunks(text: str, max_chars: int) -> List[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")

    text = normalize_text(text)
    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    sentences = _SENTENCE_BOUNDARY_RE.split(text)

    current: List[str] = []
    current_len = 0

    def flush_current() -> None:
        nonlocal current, current_len
        if current:
            chunks.append(" ".join(current).strip())
            current = []
            current_len = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if len(sentence) > max_chars:
            flush_current()
            for i in range(0, len(sentence), max_chars):
                chunks.append(sentence[i : i + max_chars])
            continue

        projected = current_len + (1 if current else 0) + len(sentence)
        if projected <= max_chars:
            current.append(sentence)
            current_len = projected
        else:
            flush_current()
            current.append(sentence)
            current_len = len(sentence)

    flush_current()
    return chunks
