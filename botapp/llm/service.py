from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from botapp.llm.prompts import (
    MODE_AUDIO_ADAPTED,
    MODE_AUDIO_SUMMARY,
    MODE_CLOSE_TO_SOURCE,
    SYSTEM_PROMPT_VERIFIER,
    build_verifier_prompt,
    canonical_mode,
)
from botapp.llm.yandex_client import YandexLLMClient, estimate_tokens


logger = logging.getLogger(__name__)

_GARBAGE_LINE_RE = re.compile(
    r"(cookie|подпис|subscribe|share|навигац|все права защищены)", re.IGNORECASE
)


@dataclass(frozen=True)
class ArticleTTSResult:
    final_text: str
    used_fallback: bool
    provider: str
    model: str
    model_uri: str
    success: bool
    error_type: str | None
    input_chars: int
    output_chars: int
    input_paragraphs: int
    output_paragraphs: int
    was_chunked: bool
    chunk_count: int
    was_truncated: bool
    retry_count: int
    latency_ms: int
    estimated_prompt_tokens: int
    estimated_completion_tokens: int
    estimated_total_tokens: int
    estimation_method: str


@dataclass(frozen=True)
class VerificationResult:
    status: str
    repaired_text: str
    reason: str
    unsupported_claims: list[str]


class ArticleLLMService:
    def __init__(
        self,
        *,
        enabled: bool,
        provider: str,
        model: str,
        max_input_chars: int,
        log_prompts: bool,
        client: YandexLLMClient | None = None,
    ) -> None:
        self.enabled = enabled
        self.provider = provider
        self.model = model
        self.max_input_chars = max_input_chars
        self.log_prompts = log_prompts
        self.client = client

    async def build_tts_text_for_article(
        self,
        title: str | None,
        body_text: str,
        source_url: str | None = None,
        mode: str = MODE_CLOSE_TO_SOURCE,
        target_duration_sec: int | None = None,
        hard_cap_sec: int | None = None,
        word_budget: int | None = None,
    ) -> ArticleTTSResult:
        mode = canonical_mode(mode)
        body = self._cleanup_body(body_text)
        fallback_text = self._assemble_text(title, body)
        paragraphs = [p for p in body.split("\n\n") if p.strip()]
        input_chars = len(fallback_text)
        input_paragraphs = len(paragraphs)

        chunks, was_truncated = self._chunk_paragraphs(
            title=title, paragraphs=paragraphs
        )
        was_chunked = len(chunks) > 1

        if not self.enabled or self.provider != "yandex" or self.client is None:
            return self._fallback_result(
                fallback_text=fallback_text,
                input_chars=input_chars,
                input_paragraphs=input_paragraphs,
                was_chunked=was_chunked,
                chunk_count=len(chunks),
                was_truncated=was_truncated,
            )

        normalized_chunks: list[str] = []
        prompt_tokens = completion_tokens = latency_ms = retries = 0

        for index, chunk in enumerate(chunks):
            chunk_title = title if index == 0 else None
            chunk_result = await self.client.normalize_article(
                title=chunk_title,
                body_text=chunk,
                source_url=source_url,
                mode=mode,
                target_duration_sec=target_duration_sec,
                hard_cap_sec=hard_cap_sec,
                word_budget=word_budget,
            )
            prompt_tokens += chunk_result.estimated_prompt_tokens
            completion_tokens += chunk_result.estimated_completion_tokens
            latency_ms += chunk_result.latency_ms
            retries += chunk_result.retry_count
            if not chunk_result.success:
                return self._fallback_result(
                    fallback_text=fallback_text,
                    input_chars=input_chars,
                    input_paragraphs=input_paragraphs,
                    was_chunked=was_chunked,
                    chunk_count=len(chunks),
                    was_truncated=was_truncated,
                    error_type=chunk_result.error_type,
                    retry_count=retries,
                    latency_ms=latency_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            normalized_chunks.append(chunk_result.output_text)

        assembled = self._assemble_from_chunks(title=title, chunks=normalized_chunks)
        return ArticleTTSResult(
            final_text=assembled,
            used_fallback=False,
            provider=self.provider,
            model=self.model,
            model_uri=self.client.model_uri,
            success=True,
            error_type=None,
            input_chars=input_chars,
            output_chars=len(assembled),
            input_paragraphs=input_paragraphs,
            output_paragraphs=len([p for p in assembled.split("\n\n") if p.strip()]),
            was_chunked=was_chunked,
            chunk_count=len(chunks),
            was_truncated=was_truncated,
            retry_count=retries,
            latency_ms=latency_ms,
            estimated_prompt_tokens=prompt_tokens,
            estimated_completion_tokens=completion_tokens,
            estimated_total_tokens=prompt_tokens + completion_tokens,
            estimation_method="local_heuristic",
        )

    async def verify_and_repair(
        self, *, source_title: str | None, source_body: str, draft_text: str, mode: str
    ) -> VerificationResult:
        mode = canonical_mode(mode)
        if mode not in {MODE_AUDIO_ADAPTED, MODE_AUDIO_SUMMARY}:
            return VerificationResult(
                status="pass",
                repaired_text=draft_text,
                reason="skipped",
                unsupported_claims=[],
            )

        deterministic_claims = self._deterministic_verify(
            source_body=source_body, draft_text=draft_text
        )
        if not deterministic_claims and (
            not self.enabled or self.provider != "yandex" or self.client is None
        ):
            return VerificationResult(
                status="pass",
                repaired_text=draft_text,
                reason="deterministic",
                unsupported_claims=[],
            )
        if not self.enabled or self.provider != "yandex" or self.client is None:
            return VerificationResult(
                status="failed",
                repaired_text=self._assemble_text(source_title, source_body),
                reason="llm_unavailable",
                unsupported_claims=deterministic_claims,
            )

        verifier_user = build_verifier_prompt(
            source_title=source_title, source_body=source_body, draft_text=draft_text
        )
        raw = await self.client.complete(
            system_prompt=SYSTEM_PROMPT_VERIFIER,
            user_prompt=verifier_user,
            input_chars=len(source_body) + len(draft_text),
            max_tokens=2500,
        )
        if not raw.success or not raw.output_text.strip():
            return VerificationResult(
                status="failed",
                repaired_text=self._assemble_text(source_title, source_body),
                reason="verifier_error",
                unsupported_claims=deterministic_claims,
            )

        parsed = self._parse_verifier_output(raw.output_text)
        if parsed["decision"] == "pass":
            return VerificationResult(
                status="pass",
                repaired_text=draft_text,
                reason=parsed["reason"],
                unsupported_claims=[],
            )
        if parsed["decision"] == "repair" and str(parsed["repaired_text"]).strip():
            repaired = str(parsed["repaired_text"]).strip()
            if not self._deterministic_verify(
                source_body=source_body, draft_text=repaired
            ):
                return VerificationResult(
                    status="repaired",
                    repaired_text=repaired,
                    reason=str(parsed["reason"]),
                    unsupported_claims=[str(x) for x in parsed["unsupported_claims"]],
                )
        return VerificationResult(
            status="failed",
            repaired_text=self._assemble_text(source_title, source_body),
            reason=str(parsed["reason"]),
            unsupported_claims=deterministic_claims
            or [str(x) for x in parsed["unsupported_claims"]],
        )

    def analytics_properties(
        self,
        *,
        result: ArticleTTSResult,
        title: str | None,
        source_url: str | None,
        user_id: int | None,
        chat_id: int | None,
    ) -> dict[str, object]:
        return {
            "provider": result.provider,
            "model": self.model,
            "model_uri": result.model_uri,
            "flow": "article_to_tts",
            "source_type": "url",
            "source_domain": urlparse(source_url).netloc if source_url else "",
            "source_url_hash": hashlib.sha256(
                (source_url or "").encode("utf-8")
            ).hexdigest()
            if source_url
            else "",
            "article_has_title": bool((title or "").strip()),
            "input_chars": result.input_chars,
            "output_chars": result.output_chars,
            "input_paragraphs": result.input_paragraphs,
            "output_paragraphs": result.output_paragraphs,
            "was_chunked": result.was_chunked,
            "chunk_count": result.chunk_count,
            "was_truncated": result.was_truncated,
            "retry_count": result.retry_count,
            "latency_ms": result.latency_ms,
            "success": result.success,
            "error_type": result.error_type,
            "estimated_prompt_tokens": result.estimated_prompt_tokens,
            "estimated_completion_tokens": result.estimated_completion_tokens,
            "estimated_total_tokens": result.estimated_total_tokens,
            "estimation_method": result.estimation_method,
            "user_id": user_id,
            "chat_id": chat_id,
        }

    def _cleanup_body(self, body_text: str) -> str:
        body = re.sub(r"\r\n?", "\n", body_text or "")
        blocks = [re.sub(r"\s+", " ", b).strip() for b in re.split(r"\n\s*\n", body)]
        filtered = [b for b in blocks if b and not _GARBAGE_LINE_RE.search(b)]
        return "\n\n".join(filtered)

    def _assemble_text(self, title: str | None, body: str) -> str:
        safe_title = (title or "").strip() or "Без названия"
        return f"{safe_title}\n\n{body.strip()}".strip()

    def _strip_title_block(self, text: str) -> str:
        lines = text.splitlines()
        if len(lines) >= 2 and lines[1].strip() == "":
            return "\n".join(lines[2:]).strip()
        return text.strip()

    def _extract_claim_markers(self, text: str) -> set[str]:
        numbers = set(re.findall(r"\b\d+[\d.,%]*\b", text))
        years = set(re.findall(r"\b(?:19|20)\d{2}\b", text))
        named_like = {
            m.group(0).strip()
            for m in re.finditer(r"\b[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z][а-яёa-z]+\b", text)
        }
        quotes = {q.strip() for q in re.findall(r"[«\"]([^»\"]{8,120})[»\"]", text)}
        causals = {
            c.strip()
            for c in re.findall(
                r"[^.!?]{0,80}(?:потому что|поэтому|в результате|из-за|привело к|следовательно)[^.!?]{0,80}",
                text,
                flags=re.IGNORECASE,
            )
        }
        return numbers | years | named_like | quotes | causals

    def _deterministic_verify(self, *, source_body: str, draft_text: str) -> list[str]:
        source_markers = self._extract_claim_markers(
            self._strip_title_block(source_body)
        )
        draft_markers = self._extract_claim_markers(self._strip_title_block(draft_text))
        unsupported = sorted(m for m in draft_markers if m and m not in source_markers)
        return unsupported[:20]

    def _parse_verifier_output(self, text: str) -> dict[str, object]:
        try:
            payload = json.loads(text)
            unsupported_claims = payload.get("unsupported_claims", [])
            if not isinstance(unsupported_claims, list):
                unsupported_claims = []
            return {
                "decision": payload.get("decision", "fail"),
                "reason": payload.get("reason", ""),
                "unsupported_claims": [str(x) for x in unsupported_claims],
                "repaired_text": payload.get("repaired_text", ""),
            }
        except Exception:
            return {
                "decision": "fail",
                "reason": "bad_json",
                "unsupported_claims": [],
                "repaired_text": "",
            }

    def _chunk_paragraphs(
        self, *, title: str | None, paragraphs: list[str]
    ) -> tuple[list[str], bool]:
        if not paragraphs:
            return [""], False
        chunks: list[str] = []
        current = ""
        for idx, paragraph in enumerate(paragraphs):
            prefix = f"{(title or '').strip()}\n\n" if idx == 0 and title else ""
            candidate = (current + "\n\n" + paragraph).strip() if current else paragraph
            if len(prefix + candidate) <= self.max_input_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
                current = paragraph
                continue
            return chunks or [""], True
        if current:
            chunks.append(current)
        return chunks, False

    def _assemble_from_chunks(self, *, title: str | None, chunks: list[str]) -> str:
        if not chunks:
            return self._assemble_text(title, "")
        first = chunks[0].strip()
        lines = [ln for ln in first.splitlines()]
        if len(lines) >= 2 and lines[1].strip() == "":
            normalized_title = lines[0].strip()
            first_body = "\n".join(lines[2:]).strip()
            all_body = "\n\n".join(
                [first_body] + [c.strip() for c in chunks[1:] if c.strip()]
            ).strip()
            return self._assemble_text(normalized_title, all_body)
        return self._assemble_text(title, "\n\n".join(chunks))

    def _fallback_result(
        self,
        *,
        fallback_text: str,
        input_chars: int,
        input_paragraphs: int,
        was_chunked: bool,
        chunk_count: int,
        was_truncated: bool,
        error_type: str | None = None,
        retry_count: int = 0,
        latency_ms: int = 0,
        prompt_tokens: int | None = None,
        completion_tokens: int = 0,
    ) -> ArticleTTSResult:
        prompt = (
            prompt_tokens
            if prompt_tokens is not None
            else estimate_tokens(fallback_text)
        )
        return ArticleTTSResult(
            final_text=fallback_text,
            used_fallback=True,
            provider=self.provider,
            model=self.model,
            model_uri=self.client.model_uri if self.client else "",
            success=False if error_type else True,
            error_type=error_type,
            input_chars=input_chars,
            output_chars=len(fallback_text),
            input_paragraphs=input_paragraphs,
            output_paragraphs=len(
                [p for p in fallback_text.split("\n\n") if p.strip()]
            ),
            was_chunked=was_chunked,
            chunk_count=chunk_count,
            was_truncated=was_truncated,
            retry_count=retry_count,
            latency_ms=latency_ms,
            estimated_prompt_tokens=prompt,
            estimated_completion_tokens=completion_tokens,
            estimated_total_tokens=prompt + completion_tokens,
            estimation_method="local_heuristic",
        )
