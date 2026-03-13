from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from botapp.extractors.url_text import fetch_article_content
from botapp.llm.prompts import (
    MODE_AUDIO_ADAPTED,
    MODE_AUDIO_SUMMARY,
    canonical_mode,
)
from botapp.llm.service import ArticleLLMService


logger = logging.getLogger(__name__)

ArticleMode = Literal[
    "close_to_source",
    "audio_adapted",
    "audio_summary",
    "near_verbatim",
    "readable_cleaned",
]
Decision = Literal["pass", "pass_with_warnings", "llm_fallback"]
Status = Literal["ok", "partial", "failed"]

SOFT_TARGET_SECONDS = {
    MODE_AUDIO_ADAPTED: 14 * 60,
    MODE_AUDIO_SUMMARY: 160,
}
HARD_CAP_SECONDS = {
    MODE_AUDIO_ADAPTED: 15 * 60,
    MODE_AUDIO_SUMMARY: 3 * 60,
}

_BOILERPLATE_MARKERS = (
    "подпис",
    "читайте также",
    "поделиться",
    "все новости",
    "политика конфиденциальности",
    "cookie",
    "регистрац",
    "войти",
    "рекоменд",
)
_EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff\u2600-\u27bf\ufe0f\u200d]+", flags=re.UNICODE
)
_BULLET_RE = re.compile(r"^\s*(?:[-*•●◦▪—]+|\d+[.)])\s+")


@dataclass(frozen=True)
class QualityReport:
    quality_score: float
    decision: Decision
    flags: list[str]


@dataclass(frozen=True)
class ProcessingTrace:
    fetched_with_browser: bool
    rule_based_extractor_used: bool
    llm_used: bool
    verifier_status: str
    tts_normalization_used: bool
    estimated_duration_before: float
    estimated_duration_after: float
    compression_attempts: int
    hard_trim_applied: bool


@dataclass(frozen=True)
class PipelineResult:
    status: Status
    url: str
    final_url: str
    mode: str
    title: str
    subtitle: str | None
    author: str | None
    published_at: str | None
    text: str
    metadata: dict[str, object]
    quality_report: QualityReport
    processing_trace: ProcessingTrace
    warnings: list[str]


def _word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def _char_quality_ratio(text: str) -> float:
    if not text:
        return 0.0
    alpha = len(re.findall(r"[A-Za-zА-Яа-яЁё]", text))
    return alpha / max(1, len(text))


def evaluate_quality(*, title: str, body_text: str) -> QualityReport:
    flags: list[str] = []
    score = 1.0
    words = _word_count(body_text)
    chars = len(body_text)
    paragraphs = len([p for p in body_text.split("\n\n") if p.strip()])
    link_hits = len(re.findall(r"https?://|www\.", body_text, flags=re.IGNORECASE))
    if chars < 500 or words < 90:
        flags.append("too_short")
        score -= 0.35
    if chars > 25000:
        flags.append("too_long")
        score -= 0.2
    if paragraphs < 3:
        flags.append("too_few_paragraphs")
        score -= 0.2
    if link_hits > 8:
        flags.append("too_many_links")
        score -= 0.2
    if _char_quality_ratio(body_text) < 0.55:
        flags.append("low_text_quality")
        score -= 0.25
    lowered = body_text.lower()
    if sum(1 for marker in _BOILERPLATE_MARKERS if marker in lowered) >= 2:
        flags.append("boilerplate_markers")
        score -= 0.25
    title_words = {
        w for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", (title or "").lower())
    }
    body_words = {w for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", lowered)}
    if title_words and len(title_words.intersection(body_words)) <= 1:
        flags.append("title_body_mismatch")
        score -= 0.2
    score = max(0.0, round(score, 3))
    decision: Decision = (
        "llm_fallback"
        if score < 0.45 or "too_short" in flags
        else ("pass_with_warnings" if flags else "pass")
    )
    return QualityReport(quality_score=score, decision=decision, flags=flags)


def estimate_audio_duration(
    text: str, speech_rate_wpm: int = 150, sentence_pause_sec: float = 0.22
) -> float:
    words = max(1, _word_count(text))
    sentences = max(1, len([s for s in re.split(r"(?<=[.!?…])\s+", text) if s.strip()]))
    return round(
        words / max(80, speech_rate_wpm) * 60 + sentence_pause_sec * sentences, 2
    )


def _hard_trim_to_duration(text: str, hard_cap_sec: int) -> tuple[str, bool]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", text) if s.strip()]
    out: list[str] = []
    for s in sentences:
        candidate = (" ".join(out + [s])).strip()
        if estimate_audio_duration(candidate) > hard_cap_sec:
            break
        out.append(s)
    return (" ".join(out) if out else text[:1200]).strip(), True


def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text)


def _normalize_lists(text: str) -> str:
    lines = text.splitlines()
    result: list[str] = []
    idx = 0
    for line in lines:
        if _BULLET_RE.match(line):
            idx += 1
            body = _BULLET_RE.sub("", line).strip()
            result.append(f"Пункт {idx}. {body}")
        else:
            idx = 0
            result.append(line)
    return "\n".join(result)


def _normalize_for_tts(text: str) -> str:
    normalized = re.sub(r"\r\n?", "\n", text)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"\s+(https?://\S+)", "", normalized)
    normalized = normalized.replace("…", "...").replace("—", " — ")
    normalized = re.sub(r"[\*_`#>]", "", normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized)
    return normalized.strip()


async def run_article_pipeline(
    *, url: str, mode: ArticleMode, timeout_seconds: int, llm_service: ArticleLLMService
) -> PipelineResult:
    warnings: list[str] = []
    resolved_mode = canonical_mode(mode)
    content = await fetch_article_content(url, timeout_seconds=timeout_seconds)
    quality = evaluate_quality(title=content.title, body_text=content.body_text)

    if not content.body_text.strip() and resolved_mode in {
        MODE_AUDIO_ADAPTED,
        MODE_AUDIO_SUMMARY,
    }:
        return PipelineResult(
            status="failed",
            url=url,
            final_url=url,
            mode=resolved_mode,
            title=content.title,
            subtitle=None,
            author=None,
            published_at=None,
            text="",
            metadata={"reason": "empty_extracted_body"},
            quality_report=quality,
            processing_trace=ProcessingTrace(
                False, True, False, "failed", True, 0.0, 0.0, 0, False
            ),
            warnings=["controlled_failure_empty_extraction"],
        )

    llm_used = False
    verifier_status = "skipped"
    compression_attempts = 0
    hard_trim_applied = False

    text = f"{content.title}\n\n{content.body_text}".strip()
    text = _normalize_lists(_strip_emoji(text))

    should_use_llm = (
        resolved_mode in {MODE_AUDIO_ADAPTED, MODE_AUDIO_SUMMARY}
    ) or quality.decision == "llm_fallback"
    if should_use_llm:
        llm_result = await llm_service.build_tts_text_for_article(
            title=content.title,
            body_text=content.body_text,
            source_url=url,
            mode=resolved_mode,
        )
        llm_used = not llm_result.used_fallback
        text = llm_result.final_text if llm_result.final_text.strip() else text

    est_before = estimate_audio_duration(text)
    hard_cap = HARD_CAP_SECONDS.get(resolved_mode)
    soft_target = SOFT_TARGET_SECONDS.get(resolved_mode)

    if resolved_mode in {MODE_AUDIO_ADAPTED, MODE_AUDIO_SUMMARY}:
        verify = await llm_service.verify_and_repair(
            source_title=content.title,
            source_body=content.body_text,
            draft_text=text,
            mode=resolved_mode,
        )
        verifier_status = verify.status
        text = verify.repaired_text
        if verify.status == "failed":
            warnings.append("verifier_failed")

    if soft_target and estimate_audio_duration(text) > soft_target:
        compression_attempts += 1
        compressed = await llm_service.build_tts_text_for_article(
            title=content.title,
            body_text=content.body_text,
            source_url=url,
            mode=resolved_mode,
        )
        if compressed.final_text.strip():
            text = compressed.final_text

    if hard_cap and estimate_audio_duration(text) > hard_cap:
        compression_attempts += 1
        text, hard_trim_applied = _hard_trim_to_duration(text, hard_cap)
        warnings.append("hard_trim_applied")

    text = _normalize_for_tts(_normalize_lists(_strip_emoji(text)))
    est_after = estimate_audio_duration(text)

    status: Status = "ok" if text else "failed"
    if warnings and status == "ok":
        status = "partial"

    domain = urlparse(url).netloc
    return PipelineResult(
        status=status,
        url=url,
        final_url=url,
        mode=resolved_mode,
        title=content.title,
        subtitle=None,
        author=None,
        published_at=None,
        text=text,
        metadata={
            "lang": None,
            "domain": domain,
            "word_count": _word_count(text),
            "char_count": len(text),
        },
        quality_report=quality,
        processing_trace=ProcessingTrace(
            fetched_with_browser=False,
            rule_based_extractor_used=True,
            llm_used=llm_used,
            verifier_status=verifier_status,
            tts_normalization_used=True,
            estimated_duration_before=est_before,
            estimated_duration_after=est_after,
            compression_attempts=compression_attempts,
            hard_trim_applied=hard_trim_applied,
        ),
        warnings=warnings,
    )
