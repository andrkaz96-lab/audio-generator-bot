import httpx
import os
import unittest

from botapp.extractors.article_pipeline import run_article_pipeline
from botapp.llm.service import ArticleLLMService


URLS = [
    "https://incrussia.ru/robots/shadow-ai-v-msb-2026/",
    "https://gopractice.ru/stories/do_things_that_dont_scale/",
]
MODES = ["near_verbatim", "readable_cleaned"]


@unittest.skipUnless(os.getenv("RUN_LIVE_URL_TESTS") == "1", "Set RUN_LIVE_URL_TESTS=1 to run live URL checks")
class LiveArticleUrlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_on_live_urls_for_both_modes(self):
        service = ArticleLLMService(
            enabled=False,
            provider="yandex",
            model="yandexgpt-lite/latest",
            max_input_chars=18000,
            log_prompts=False,
            client=None,
        )

        for url in URLS:
            for mode in MODES:
                with self.subTest(url=url, mode=mode):
                    try:
                        result = await run_article_pipeline(
                            url=url,
                            mode=mode,
                            timeout_seconds=30,
                            llm_service=service,
                        )
                    except (httpx.HTTPError, OSError) as exc:
                        self.skipTest(f"Live URL test skipped due to network/proxy limitation: {exc}")
                    self.assertIn(result.status, {"ok", "partial"})
                    self.assertGreater(len(result.text), 300)
                    self.assertEqual(result.mode, mode)


if __name__ == "__main__":
    unittest.main()
