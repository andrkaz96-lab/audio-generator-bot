from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from botapp.llm.prompts import build_user_prompt, system_prompt_for_mode


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403}


@dataclass(frozen=True)
class LLMCallResult:
    output_text: str
    provider: str
    model_uri: str
    success: bool
    error_type: str | None
    latency_ms: int
    input_chars: int
    output_chars: int
    estimated_prompt_tokens: int
    estimated_completion_tokens: int
    estimated_total_tokens: int
    estimation_method: str
    retry_count: int


def estimate_tokens(text: str) -> int:
    # Conservative heuristic for ru/en plain text.
    return max(1, len(text) // 4)


logger = logging.getLogger(__name__)


class YandexLLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        folder_id: str,
        api_base: str = "https://llm.api.cloud.yandex.net/v1",
        timeout_seconds: int = 30,
        temperature: float = 0.1,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key.strip()
        self.folder_id = folder_id.strip()
        self.api_base = api_base.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_retries = max_retries

    @property
    def model_uri(self) -> str:
        return f"gpt://{self.folder_id}/yandexgpt-lite"

    async def normalize_article(
        self,
        *,
        title: str | None,
        body_text: str,
        source_url: str | None,
        mode: str = "near_verbatim",
    ) -> LLMCallResult:
        system_prompt = system_prompt_for_mode(mode)
        user_prompt = build_user_prompt(title=title, body_text=body_text, source_url=source_url, mode=mode)
        endpoint = "/chat/completions"
        payload = {
            "model": self.model_uri,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 7000,
        }

        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "x-folder-id": self.folder_id,
            "Content-Type": "application/json",
        }

        prompt_tokens = estimate_tokens(system_prompt + "\n" + user_prompt)
        request_started = time.perf_counter()
        last_error: str | None = None

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(
                        f"{self.api_base}{endpoint}",
                        json=payload,
                        headers=headers,
                    )
                logger.info(
                    "LLM request completed",
                    extra={
                        "provider": "yandex",
                        "base_url": self.api_base,
                        "endpoint": endpoint,
                        "model_uri": self.model_uri,
                        "status_code": response.status_code,
                        "success": response.status_code < 400,
                        "latency_ms": int((time.perf_counter() - request_started) * 1000),
                    },
                )

                if response.status_code in NON_RETRYABLE_STATUS_CODES:
                    logger.error(
                        "LLM request failed with non-retryable status",
                        extra={
                            "provider": "yandex",
                            "base_url": self.api_base,
                            "endpoint": endpoint,
                            "model_uri": self.model_uri,
                            "success": False,
                            "status_code": response.status_code,
                            "error_body": getattr(response, "text", "")[:500],
                            "latency_ms": int((time.perf_counter() - request_started) * 1000),
                        },
                    )
                    return self._error_result(
                        error_type=f"HTTP_{response.status_code}",
                        latency_ms=int((time.perf_counter() - request_started) * 1000),
                        input_chars=len(body_text) + len(title or ""),
                        prompt_tokens=prompt_tokens,
                        retry_count=attempt,
                    )

                if response.status_code in RETRYABLE_STATUS_CODES:
                    last_error = f"HTTP_{response.status_code}"
                    if attempt < self.max_retries:
                        await asyncio.sleep(2**attempt)
                        continue
                    logger.error(
                        "LLM request failed after retries",
                        extra={
                            "provider": "yandex",
                            "base_url": self.api_base,
                            "endpoint": endpoint,
                            "model_uri": self.model_uri,
                            "success": False,
                            "status_code": response.status_code,
                            "error_body": getattr(response, "text", "")[:500],
                            "latency_ms": int((time.perf_counter() - request_started) * 1000),
                        },
                    )
                    return self._error_result(
                        error_type=last_error,
                        latency_ms=int((time.perf_counter() - request_started) * 1000),
                        input_chars=len(body_text) + len(title or ""),
                        prompt_tokens=prompt_tokens,
                        retry_count=attempt,
                    )

                response.raise_for_status()
                data = response.json()
                choices = data.get("choices", [])
                output = ""
                if choices:
                    message = choices[0].get("message") or {}
                    output = message.get("content", "")
                output = output.strip()
                completion_tokens = estimate_tokens(output)
                return LLMCallResult(
                    output_text=output,
                    provider="yandex",
                    model_uri=self.model_uri,
                    success=bool(output),
                    error_type=None if output else "EmptyOutput",
                    latency_ms=int((time.perf_counter() - request_started) * 1000),
                    input_chars=len(body_text) + len(title or ""),
                    output_chars=len(output),
                    estimated_prompt_tokens=prompt_tokens,
                    estimated_completion_tokens=completion_tokens,
                    estimated_total_tokens=prompt_tokens + completion_tokens,
                    estimation_method="local_heuristic",
                    retry_count=attempt,
                )
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_error = type(exc).__name__
                logger.error(
                    "LLM transport error",
                    extra={
                        "provider": "yandex",
                        "base_url": self.api_base,
                        "endpoint": endpoint,
                        "model_uri": self.model_uri,
                        "success": False,
                        "status_code": None,
                        "error_body": str(exc),
                        "latency_ms": int((time.perf_counter() - request_started) * 1000),
                    },
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
            except Exception as exc:
                last_error = type(exc).__name__
                logger.exception(
                    "LLM unexpected error",
                    extra={
                        "provider": "yandex",
                        "base_url": self.api_base,
                        "endpoint": endpoint,
                        "model_uri": self.model_uri,
                        "success": False,
                        "status_code": None,
                        "error_body": str(exc),
                        "latency_ms": int((time.perf_counter() - request_started) * 1000),
                    },
                )
                break

        return self._error_result(
            error_type=last_error or "UnknownError",
            latency_ms=int((time.perf_counter() - request_started) * 1000),
            input_chars=len(body_text) + len(title or ""),
            prompt_tokens=prompt_tokens,
            retry_count=self.max_retries,
        )

    def _error_result(
        self,
        *,
        error_type: str,
        latency_ms: int,
        input_chars: int,
        prompt_tokens: int,
        retry_count: int,
    ) -> LLMCallResult:
        return LLMCallResult(
            output_text="",
            provider="yandex",
            model_uri=self.model_uri,
            success=False,
            error_type=error_type,
            latency_ms=latency_ms,
            input_chars=input_chars,
            output_chars=0,
            estimated_prompt_tokens=prompt_tokens,
            estimated_completion_tokens=0,
            estimated_total_tokens=prompt_tokens,
            estimation_method="local_heuristic",
            retry_count=retry_count,
        )
