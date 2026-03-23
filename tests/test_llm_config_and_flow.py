import os
import tempfile
import unittest
from unittest.mock import patch

from botapp.config import load_settings
from botapp.llm.service import ArticleLLMService, ArticleTTSResult


class ConfigTests(unittest.TestCase):
    def test_env_priority_for_folder_id(self):
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "1:abc",
                "YANDEX_FOLDER_ID": "env-folder",
            },
            clear=False,
        ):
            settings = load_settings()
            self.assertEqual(settings.yandex_folder_id, "env-folder")

    def test_folder_default_when_missing(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "1:abc"}, clear=True):
            settings = load_settings()
            self.assertEqual(settings.yandex_folder_id, "b1geq9r8nerbilj0i53p")


class ServicePayloadTests(unittest.TestCase):
    def test_analytics_payload_has_stable_fields(self):
        service = ArticleLLMService(
            enabled=False,
            provider="yandex",
            model="yandexgpt-lite/latest",
            max_input_chars=18000,
            log_prompts=False,
            client=None,
        )
        result = ArticleTTSResult(
            final_text="T\n\nB",
            used_fallback=True,
            provider="yandex",
            model="yandexgpt-lite/latest",
            model_uri="",
            success=False,
            error_type="HTTP_500",
            input_chars=3,
            output_chars=3,
            input_paragraphs=1,
            output_paragraphs=1,
            was_chunked=False,
            chunk_count=1,
            was_truncated=False,
            retry_count=2,
            latency_ms=1,
            estimated_prompt_tokens=1,
            estimated_completion_tokens=1,
            estimated_total_tokens=2,
            estimation_method="local_heuristic",
        )
        payload = service.analytics_properties(
            result=result,
            title="T",
            source_url="https://example.com/path",
            user_id=1,
            chat_id=2,
        )
        self.assertEqual(payload["flow"], "article_to_tts")
        self.assertEqual(payload["source_type"], "url")
        self.assertTrue(payload["source_url_hash"])

    def test_debug_txt_exact_match(self):
        text = "Заголовок\n\nТело статьи"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "article_tts_text_1.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            with open(path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), text)


if __name__ == "__main__":
    unittest.main()
