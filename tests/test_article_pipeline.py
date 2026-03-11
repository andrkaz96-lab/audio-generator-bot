import unittest
from unittest.mock import AsyncMock, patch

from botapp.extractors.article_pipeline import evaluate_quality, run_article_pipeline
from botapp.extractors.url_text import ArticleContent


class QualityEvaluatorTests(unittest.TestCase):
    def test_quality_flags_short_and_boilerplate(self):
        report = evaluate_quality(
            title="AI в ритейле",
            body_text="Подписаться. Политика конфиденциальности. cookie banner",
        )
        self.assertEqual(report.decision, "llm_fallback")
        self.assertIn("too_short", report.flags)


class PipelineFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_readable_mode_calls_llm_cleanup(self):
        content = ArticleContent(
            title="Заголовок",
            body_text="Первый абзац статьи.\n\nВторой абзац статьи с деталями.",
            full_text="Заголовок\n\nПервый абзац статьи.\n\nВторой абзац статьи с деталями.",
        )

        llm_result = AsyncMock()
        llm_result.final_text = "Заголовок\n\nАдаптированный текст"
        llm_result.used_fallback = False

        llm_service = AsyncMock()
        llm_service.build_tts_text_for_article = AsyncMock(return_value=llm_result)

        with patch("botapp.extractors.article_pipeline.fetch_article_content", AsyncMock(return_value=content)):
            result = await run_article_pipeline(
                url="https://example.com/article",
                mode="readable_cleaned",
                timeout_seconds=10,
                llm_service=llm_service,
            )

        self.assertEqual(result.mode, "readable_cleaned")
        self.assertTrue(result.processing_trace.llm_used)
        llm_service.build_tts_text_for_article.assert_awaited_once()
        self.assertEqual(llm_service.build_tts_text_for_article.await_args.kwargs["mode"], "readable_cleaned")


if __name__ == "__main__":
    unittest.main()
