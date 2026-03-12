from __future__ import annotations

import asyncio

import httpx

from botapp.extractors.article_pipeline import run_article_pipeline
from botapp.llm.service import ArticleLLMService


URLS = [
    "https://incrussia.ru/robots/shadow-ai-v-msb-2026/",
    "https://gopractice.ru/stories/do_things_that_dont_scale/",
]
MODES = ["near_verbatim", "readable_cleaned"]


async def main() -> None:
    service = ArticleLLMService(
        enabled=False,
        provider="yandex",
        model="yandexgpt-lite/latest",
        max_input_chars=18000,
        log_prompts=False,
        client=None,
    )

    had_errors = False
    for url in URLS:
        for mode in MODES:
            try:
                result = await run_article_pipeline(
                    url=url,
                    mode=mode,
                    timeout_seconds=30,
                    llm_service=service,
                )
                print(
                    f"[{mode}] {url}\n"
                    f"  status={result.status} chars={len(result.text)} "
                    f"score={result.quality_report.quality_score} "
                    f"decision={result.quality_report.decision} "
                    f"llm_used={result.processing_trace.llm_used}\n"
                )
            except (httpx.HTTPError, OSError) as exc:
                had_errors = True
                print(f"[{mode}] {url}\n  WARNING: network/proxy limitation: {exc}\n")

    if had_errors:
        print("Completed with network warnings.")


if __name__ == "__main__":
    asyncio.run(main())
