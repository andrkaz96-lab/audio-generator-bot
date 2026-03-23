from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
_CLAUSE_RE = re.compile(r"(?<=[,;:—-])\s+")
_PARAGRAPH_RE = re.compile(r"\n\s*\n+")
_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")


@dataclass(frozen=True)
class ChunkLimits:
    max_chars: int
    max_sentences: int
    max_words: int
    min_chars: int

    def validate(self) -> None:
        if self.max_chars <= 0:
            raise ValueError("max_chars must be > 0")
        if self.max_sentences <= 0:
            raise ValueError("max_sentences must be > 0")
        if self.max_words <= 0:
            raise ValueError("max_words must be > 0")
        if self.min_chars <= 0:
            raise ValueError("min_chars must be > 0")
        if self.min_chars > self.max_chars:
            raise ValueError("min_chars must be <= max_chars")


@dataclass(frozen=True)
class ChunkPlan:
    level_name: str
    limits: ChunkLimits
    separators: tuple[re.Pattern[str], ...]
    allow_word_split: bool = True


DEFAULT_FALLBACK_PLANS: tuple[ChunkPlan, ...] = (
    ChunkPlan(
        level_name="paragraph_sentence",
        limits=ChunkLimits(
            max_chars=1400, max_sentences=6, max_words=180, min_chars=80
        ),
        separators=(_PARAGRAPH_RE, _SENTENCE_RE),
    ),
    ChunkPlan(
        level_name="sentence_clause",
        limits=ChunkLimits(max_chars=700, max_sentences=3, max_words=90, min_chars=80),
        separators=(_SENTENCE_RE, _CLAUSE_RE),
    ),
    ChunkPlan(
        level_name="clause_words",
        limits=ChunkLimits(max_chars=320, max_sentences=2, max_words=45, min_chars=80),
        separators=(_CLAUSE_RE,),
    ),
    ChunkPlan(
        level_name="words",
        limits=ChunkLimits(max_chars=160, max_sentences=1, max_words=20, min_chars=80),
        separators=(),
    ),
)


def normalize_tts_text(text: str) -> str:
    paragraphs: list[str] = []
    for raw_paragraph in _PARAGRAPH_RE.split(text or ""):
        cleaned = _WHITESPACE_RE.sub(
            " ", raw_paragraph.replace("\r", " ").replace("\n", " ")
        ).strip()
        if cleaned:
            paragraphs.append(cleaned)
    return "\n\n".join(paragraphs)


class HierarchicalTextChunker:
    def __init__(self, plans: Iterable[ChunkPlan] | None = None) -> None:
        self._plans = tuple(plans or DEFAULT_FALLBACK_PLANS)
        if not self._plans:
            raise ValueError("At least one chunking plan is required")
        for plan in self._plans:
            plan.limits.validate()

    @property
    def plans(self) -> tuple[ChunkPlan, ...]:
        return self._plans

    def split_text(self, text: str) -> list[str]:
        normalized = normalize_tts_text(text)
        if not normalized:
            return []
        return self._split_with_plan(normalized, self._plans[0])

    def split_for_retry(self, text: str, level_index: int) -> list[str]:
        normalized = normalize_tts_text(text)
        if not normalized:
            return []
        if level_index + 1 >= len(self._plans):
            return []
        return self._split_with_plan(normalized, self._plans[level_index + 1])

    def plan_name(self, level_index: int) -> str:
        return self._plans[level_index].level_name

    def max_level_index(self) -> int:
        return len(self._plans) - 1

    def _split_with_plan(self, text: str, plan: ChunkPlan) -> list[str]:
        if len(text) <= plan.limits.max_chars and self._stats_ok(text, 1, plan.limits):
            return [text]

        chunks: list[str] = []
        self._split_recursive(text, plan, 0, chunks)
        return [chunk for chunk in chunks if chunk]

    def _split_recursive(
        self,
        text: str,
        plan: ChunkPlan,
        separator_index: int,
        out: list[str],
    ) -> None:
        text = normalize_tts_text(text)
        if not text:
            return

        if separator_index < len(plan.separators):
            pieces = [
                piece.strip()
                for piece in plan.separators[separator_index].split(text)
                if piece.strip()
            ]
            if len(pieces) > 1:
                self._pack_pieces(pieces, plan, separator_index + 1, out)
                return

        self._split_to_words(text, plan, out)

    def _pack_pieces(
        self,
        pieces: list[str],
        plan: ChunkPlan,
        next_separator_index: int,
        out: list[str],
    ) -> None:
        current: list[str] = []
        current_chars = 0
        current_sentences = 0
        current_words = 0

        def flush() -> None:
            nonlocal current, current_chars, current_sentences, current_words
            if not current:
                return
            candidate = " ".join(current).strip()
            if candidate:
                out.append(candidate)
            current = []
            current_chars = 0
            current_sentences = 0
            current_words = 0

        for piece in pieces:
            piece_chars = len(piece)
            piece_sentences = self._count_sentences(piece)
            piece_words = self._count_words(piece)
            if not self._stats_ok(piece, piece_sentences, plan.limits):
                flush()
                self._split_recursive(piece, plan, next_separator_index, out)
                continue

            projected_chars = current_chars + (1 if current else 0) + piece_chars
            projected_sentences = current_sentences + piece_sentences
            projected_words = current_words + piece_words
            if current and (
                projected_chars > plan.limits.max_chars
                or projected_sentences > plan.limits.max_sentences
                or projected_words > plan.limits.max_words
            ):
                flush()

            current.append(piece)
            current_chars = current_chars + (1 if current_chars else 0) + piece_chars
            current_sentences += piece_sentences
            current_words += piece_words

        flush()

    def _split_to_words(self, text: str, plan: ChunkPlan, out: list[str]) -> None:
        words = text.split()
        if not words:
            return

        current: list[str] = []
        current_chars = 0

        def flush() -> None:
            nonlocal current, current_chars
            if current:
                out.append(" ".join(current))
                current = []
                current_chars = 0

        for word in words:
            if len(word) > plan.limits.max_chars and plan.allow_word_split:
                flush()
                out.extend(
                    self._split_long_word(
                        word, plan.limits.max_chars, plan.limits.min_chars
                    )
                )
                continue

            projected_chars = current_chars + (1 if current else 0) + len(word)
            if current and (
                projected_chars > plan.limits.max_chars
                or len(current) >= plan.limits.max_words
            ):
                flush()

            current.append(word)
            current_chars += (1 if current_chars else 0) + len(word)

        flush()

    def _split_long_word(self, word: str, max_chars: int, min_chars: int) -> list[str]:
        if len(word) <= max_chars:
            return [word]
        if max_chars <= min_chars:
            return [word[i : i + max_chars] for i in range(0, len(word), max_chars)]

        chunks: list[str] = []
        cursor = 0
        while cursor < len(word):
            remaining = len(word) - cursor
            if remaining <= max_chars:
                chunks.append(word[cursor:])
                break
            take = max_chars
            if remaining - take < min_chars:
                take = remaining // 2
            chunks.append(word[cursor : cursor + take])
            cursor += take
        return chunks

    def _count_sentences(self, text: str) -> int:
        return max(1, len([part for part in _SENTENCE_RE.split(text) if part.strip()]))

    def _count_words(self, text: str) -> int:
        return len(text.split())

    def _stats_ok(self, text: str, sentence_count: int, limits: ChunkLimits) -> bool:
        return (
            len(text) <= limits.max_chars
            and sentence_count <= limits.max_sentences
            and self._count_words(text) <= limits.max_words
        )
