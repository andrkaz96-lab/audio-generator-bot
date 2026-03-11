from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from botapp.extractors.url_text import fetch_article_content
from botapp.llm.service import ArticleLLMService


ArticleMode = Literal["near_verbatim", "readable_cleaned"]
Decision = Literal["pass", "pass_with_warnings", "llm_fallback"]
Status = Literal["ok", "partial", "failed"]

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
    tts_normalization_used: bool


@dataclass(frozen=True)
class PipelineResult:
    status: Status
    url: str
    final_url: str
    mode: ArticleMode
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
    boilerplate_hits = sum(1 for marker in _BOILERPLATE_MARKERS if marker in lowered)
    if boilerplate_hits >= 2:
        flags.append("boilerplate_markers")
        score -= 0.25

    title_words = {w for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", (title or "").lower())}
    body_words = {w for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", lowered)}
    if title_words and len(title_words.intersection(body_words)) <= 1:
        flags.append("title_body_mismatch")
        score -= 0.2

    score = max(0.0, round(score, 3))
    if score < 0.45 or "too_short" in flags:
        decision: Decision = "llm_fallback"
    elif flags:
        decision = "pass_with_warnings"
    else:
        decision = "pass"

    return QualityReport(quality_score=score, decision=decision, flags=flags)


def _normalize_for_tts(text: str, mode: ArticleMode) -> str:
    normalized = re.sub(r"\r\n?", "\n", text)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"\s+(https?://\S+)", "", normalized)
    normalized = normalized.replace("…", "...").replace("—", " — ")
    normalized = re.sub(r"\s{2,}", " ", normalized)

    if mode == "readable_cleaned":
        normalized = normalized.replace("т.д.", "и так далее")
        normalized = normalized.replace("т.п.", "и тому подобное")

    return normalized.strip()


async def run_article_pipeline(
    *,
    url: str,
    mode: ArticleMode,
    timeout_seconds: int,
    llm_service: ArticleLLMService,
) -> PipelineResult:
    warnings: list[str] = []
    content = await fetch_article_content(url, timeout_seconds=timeout_seconds)
    quality = evaluate_quality(title=content.title, body_text=content.body_text)

    text = content.full_text
    llm_used = False

    if quality.decision == "llm_fallback":
        llm_result = await llm_service.build_tts_text_for_article(
            title=content.title,
            body_text=content.body_text,
            source_url=url,
            mode=mode,
        )
        llm_used = not llm_result.used_fallback
        text = llm_result.final_text
        if llm_result.used_fallback and not text.strip():
            warnings.append("llm_fallback_failed")

    elif mode == "readable_cleaned":
        llm_result = await llm_service.build_tts_text_for_article(
            title=content.title,
            body_text=content.body_text,
            source_url=url,
            mode=mode,
        )
        text = llm_result.final_text
        llm_used = not llm_result.used_fallback

    text = _normalize_for_tts(text, mode)

    status: Status = "ok" if text else "failed"
    if warnings and status == "ok":
        status = "partial"

    final_url = url
    domain = urlparse(final_url).netloc
    return PipelineResult(
        status=status,
        url=url,
        final_url=final_url,
        mode=mode,
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
            tts_normalization_used=True,
        ),
        warnings=warnings,
    )
