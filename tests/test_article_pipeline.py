import unittest
from unittest.mock import AsyncMock, patch

from botapp.extractors.article_pipeline import (
    evaluate_quality,
    estimate_audio_duration,
    run_article_pipeline,
)
from botapp.extractors.url_text import ArticleContent


class QualityEvaluatorTests(unittest.TestCase):
    def test_quality_flags_short_and_boilerplate(self):
        report = evaluate_quality(
            title="AI в ритейле",
            body_text="Подписаться. Политика конфиденциальности. cookie banner",
        )
        self.assertEqual(report.decision, "llm_fallback")
        self.assertIn("too_short", report.flags)

    def test_duration_estimator_positive(self):
        duration = estimate_audio_duration("Привет. Это тестовый текст для озвучки.")
        self.assertGreater(duration, 1)


class PipelineFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_to_source_skips_llm_on_pass(self):
        body = "\n\n".join(
            [
                f"Абзац {i} с достаточным количеством слов для теста пайплайна и качества."
                for i in range(1, 10)
            ]
        )
        content = ArticleContent(
            title="Заголовок", body_text=body, full_text=f"Заголовок\n\n{body}"
        )
        llm_service = AsyncMock()

        with patch(
            "botapp.extractors.article_pipeline.fetch_article_content",
            AsyncMock(return_value=content),
        ):
            result = await run_article_pipeline(
                url="https://example.com/article",
                mode="close_to_source",
                timeout_seconds=10,
                llm_service=llm_service,
            )

        self.assertFalse(result.processing_trace.llm_used)
        llm_service.build_tts_text_for_article.assert_not_called()

    async def test_audio_modes_call_llm(self):
        body = "\n\n".join(
            [
                f"Абзац {i} с достаточным количеством слов для теста адаптации под слух и проверки маршрутизации."
                for i in range(1, 10)
            ]
        )
        content = ArticleContent(
            title="Заголовок", body_text=body, full_text=f"Заголовок\n\n{body}"
        )
        llm_result = AsyncMock(
            final_text="Заголовок\n\nАдаптированный текст", used_fallback=False
        )
        verify_result = AsyncMock(
            status="pass",
            repaired_text="Заголовок\n\nАдаптированный текст",
            reason="ok",
            unsupported_claims=[],
        )
        llm_service = AsyncMock()
        llm_service.build_tts_text_for_article = AsyncMock(return_value=llm_result)
        llm_service.verify_and_repair = AsyncMock(return_value=verify_result)

        with patch(
            "botapp.extractors.article_pipeline.fetch_article_content",
            AsyncMock(return_value=content),
        ):
            adapted = await run_article_pipeline(
                url="https://example.com/article",
                mode="audio_adapted",
                timeout_seconds=10,
                llm_service=llm_service,
            )
            summary = await run_article_pipeline(
                url="https://example.com/article",
                mode="audio_summary",
                timeout_seconds=10,
                llm_service=llm_service,
            )

        self.assertTrue(adapted.processing_trace.llm_used)
        self.assertTrue(summary.processing_trace.llm_used)
        self.assertEqual(llm_service.verify_and_repair.await_count, 2)

    async def test_emoji_and_bullets_normalized(self):
        body = "• Первый пункт 😀\n• Второй пункт 😎\n\n" + " ".join(
            ["Обычный абзац с достаточным количеством слов."] * 30
        )
        content = ArticleContent(
            title="Тест", body_text=body, full_text=f"Тест\n\n{body}"
        )
        llm_service = AsyncMock()

        with patch(
            "botapp.extractors.article_pipeline.fetch_article_content",
            AsyncMock(return_value=content),
        ):
            result = await run_article_pipeline(
                url="https://example.com/article",
                mode="close_to_source",
                timeout_seconds=10,
                llm_service=llm_service,
            )

        self.assertIn("Пункт 1.", result.text)
        self.assertNotIn("😀", result.text)

    async def test_controlled_failure_on_empty_extraction_for_audio_modes(self):
        content = ArticleContent(title="Тест", body_text="", full_text="")
        llm_service = AsyncMock()
        with patch(
            "botapp.extractors.article_pipeline.fetch_article_content",
            AsyncMock(return_value=content),
        ):
            result = await run_article_pipeline(
                url="https://example.com/article",
                mode="audio_summary",
                timeout_seconds=10,
                llm_service=llm_service,
            )
        self.assertEqual(result.status, "failed")
        self.assertIn("controlled_failure_empty_extraction", result.warnings)

    async def test_hard_cap_enforced_for_summary(self):
        body = " ".join(["слово"] * 5000)
        content = ArticleContent(
            title="Заголовок", body_text=body, full_text=f"Заголовок\n\n{body}"
        )
        llm_result = AsyncMock(final_text=f"Заголовок\n\n{body}", used_fallback=False)
        verify_result = AsyncMock(
            status="pass",
            repaired_text=f"Заголовок\n\n{body}",
            reason="ok",
            unsupported_claims=[],
        )
        llm_service = AsyncMock()
        llm_service.build_tts_text_for_article = AsyncMock(return_value=llm_result)
        llm_service.verify_and_repair = AsyncMock(return_value=verify_result)
        with patch(
            "botapp.extractors.article_pipeline.fetch_article_content",
            AsyncMock(return_value=content),
        ):
            result = await run_article_pipeline(
                url="https://example.com/article",
                mode="audio_summary",
                timeout_seconds=10,
                llm_service=llm_service,
            )
        self.assertTrue(result.processing_trace.hard_trim_applied)
        self.assertLessEqual(result.processing_trace.estimated_duration_after, 180)

    async def test_alias_modes_are_preserved(self):
        body = " ".join(["Текст для проверки алиасов и обратной совместимости."] * 120)
        content = ArticleContent(
            title="Заголовок", body_text=body, full_text=f"Заголовок\n\n{body}"
        )
        llm_result = AsyncMock(
            final_text="Заголовок\n\nАдаптированный текст", used_fallback=False
        )
        verify_result = AsyncMock(
            status="pass",
            repaired_text="Заголовок\n\nАдаптированный текст",
            reason="ok",
            unsupported_claims=[],
        )
        llm_service = AsyncMock()
        llm_service.build_tts_text_for_article = AsyncMock(return_value=llm_result)
        llm_service.verify_and_repair = AsyncMock(return_value=verify_result)
        with patch(
            "botapp.extractors.article_pipeline.fetch_article_content",
            AsyncMock(return_value=content),
        ):
            near = await run_article_pipeline(
                url="https://example.com/article",
                mode="near_verbatim",
                timeout_seconds=10,
                llm_service=llm_service,
            )
            readable = await run_article_pipeline(
                url="https://example.com/article",
                mode="readable_cleaned",
                timeout_seconds=10,
                llm_service=llm_service,
            )
        self.assertEqual(near.mode, "close_to_source")
        self.assertEqual(readable.mode, "audio_adapted")

    async def test_audio_modes_use_different_budgets(self):
        body = " ".join(
            ["Длинный текст для проверки разных бюджетов по режимам."] * 500
        )
        content = ArticleContent(
            title="Заголовок", body_text=body, full_text=f"Заголовок\n\n{body}"
        )
        llm_result = AsyncMock(
            final_text="Заголовок\n\nАдаптированный текст", used_fallback=False
        )
        verify_result = AsyncMock(
            status="pass",
            repaired_text="Заголовок\n\nАдаптированный текст",
            reason="ok",
            unsupported_claims=[],
        )
        llm_service = AsyncMock()
        llm_service.build_tts_text_for_article = AsyncMock(return_value=llm_result)
        llm_service.verify_and_repair = AsyncMock(return_value=verify_result)
        with patch(
            "botapp.extractors.article_pipeline.fetch_article_content",
            AsyncMock(return_value=content),
        ):
            await run_article_pipeline(
                url="https://example.com/article",
                mode="audio_adapted",
                timeout_seconds=10,
                llm_service=llm_service,
            )
            await run_article_pipeline(
                url="https://example.com/article",
                mode="audio_summary",
                timeout_seconds=10,
                llm_service=llm_service,
            )
        adapted_budget = llm_service.build_tts_text_for_article.await_args_list[
            0
        ].kwargs["word_budget"]
        summary_budget = llm_service.build_tts_text_for_article.await_args_list[
            1
        ].kwargs["word_budget"]
        self.assertGreater(adapted_budget, summary_budget)

    async def test_long_article_mode_outputs_have_different_density(self):
        body = " ".join([f"Факт {i} с пояснением и контекстом." for i in range(1, 800)])
        content = ArticleContent(
            title="Заголовок", body_text=body, full_text=f"Заголовок\n\n{body}"
        )
        adapted_text = "Заголовок\n\n" + " ".join(
            [f"Факт {i} с пояснением." for i in range(1, 700)]
        )
        summary_text = "Заголовок\n\n" + " ".join([f"Факт {i}." for i in range(1, 320)])
        llm_service = AsyncMock()

        async def _build(**kwargs):
            mode = kwargs.get("mode")
            if mode == "audio_summary":
                return AsyncMock(final_text=summary_text, used_fallback=False)
            return AsyncMock(final_text=adapted_text, used_fallback=False)

        async def _verify(**kwargs):
            mode = kwargs.get("mode")
            if mode == "audio_summary":
                return AsyncMock(
                    status="pass",
                    repaired_text=summary_text,
                    reason="ok",
                    unsupported_claims=[],
                )
            return AsyncMock(
                status="pass",
                repaired_text=adapted_text,
                reason="ok",
                unsupported_claims=[],
            )

        llm_service.verify_and_repair = AsyncMock(side_effect=_verify)
        llm_service.build_tts_text_for_article = AsyncMock(side_effect=_build)
        with patch(
            "botapp.extractors.article_pipeline.fetch_article_content",
            AsyncMock(return_value=content),
        ):
            adapted = await run_article_pipeline(
                url="https://example.com/article",
                mode="audio_adapted",
                timeout_seconds=10,
                llm_service=llm_service,
            )
            summary = await run_article_pipeline(
                url="https://example.com/article",
                mode="audio_summary",
                timeout_seconds=10,
                llm_service=llm_service,
            )
        self.assertGreater(
            adapted.metadata["word_count"], summary.metadata["word_count"]
        )
        source_words = len(body.split())
        self.assertGreaterEqual(
            adapted.metadata["word_count"], int(source_words * 0.12)
        )
        self.assertLessEqual(summary.metadata["word_count"], int(source_words * 0.1))


if __name__ == "__main__":
    unittest.main()
