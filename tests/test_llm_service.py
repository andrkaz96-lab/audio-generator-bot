import asyncio
import unittest

from botapp.llm.service import ArticleLLMService
from botapp.llm.yandex_client import LLMCallResult, YandexLLMClient


class DummyClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.model_uri = "gpt://folder/yandexgpt-lite"

    async def normalize_article(self, *, title, body_text, source_url):
        self.calls.append((title, body_text, source_url))
        result = self.results.pop(0)
        return result


class ArticleLLMServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_when_llm_fails(self):
        client = DummyClient([
            LLMCallResult(
                output_text="",
                provider="yandex",
                model_uri="gpt://folder/yandexgpt-lite",
                success=False,
                error_type="HTTP_500",
                latency_ms=100,
                input_chars=10,
                output_chars=0,
                estimated_prompt_tokens=10,
                estimated_completion_tokens=0,
                estimated_total_tokens=10,
                estimation_method="local_heuristic",
                retry_count=2,
            )
        ])
        service = ArticleLLMService(
            enabled=True,
            provider="yandex",
            model="yandexgpt-lite/latest",
            max_input_chars=18000,
            log_prompts=False,
            client=client,
        )

        result = await service.build_tts_text_for_article(title="Заголовок", body_text="Тело", source_url="https://a.b")
        self.assertTrue(result.used_fallback)
        self.assertEqual(result.final_text, "Заголовок\n\nТело")

    async def test_chunking_and_title_once(self):
        ok = LLMCallResult(
            output_text="Заголовок\n\nПараграф 1",
            provider="yandex",
            model_uri="gpt://folder/yandexgpt-lite",
            success=True,
            error_type=None,
            latency_ms=50,
            input_chars=10,
            output_chars=20,
            estimated_prompt_tokens=3,
            estimated_completion_tokens=3,
            estimated_total_tokens=6,
            estimation_method="local_heuristic",
            retry_count=0,
        )
        ok2 = LLMCallResult(
            output_text="Параграф 2",
            provider="yandex",
            model_uri="gpt://folder/yandexgpt-lite",
            success=True,
            error_type=None,
            latency_ms=50,
            input_chars=10,
            output_chars=10,
            estimated_prompt_tokens=3,
            estimated_completion_tokens=3,
            estimated_total_tokens=6,
            estimation_method="local_heuristic",
            retry_count=0,
        )
        client = DummyClient([ok, ok2])
        service = ArticleLLMService(
            enabled=True,
            provider="yandex",
            model="yandexgpt-lite/latest",
            max_input_chars=40,
            log_prompts=False,
            client=client,
        )

        result = await service.build_tts_text_for_article(
            title="Заголовок",
            body_text="Параграф 1 очень длинный\n\nПараграф 2 очень длинный",
            source_url="https://example.com/x",
        )
        self.assertTrue(result.was_chunked)
        self.assertIn("Заголовок\n\nПараграф 1\n\nПараграф 2", result.final_text)

    async def test_service_disabled_uses_deterministic_text(self):
        service = ArticleLLMService(
            enabled=False,
            provider="yandex",
            model="yandexgpt-lite/latest",
            max_input_chars=18000,
            log_prompts=False,
            client=None,
        )
        result = await service.build_tts_text_for_article(title=None, body_text="Body")
        self.assertEqual(result.final_text, "Без названия\n\nBody")


class YandexClientModelUriTests(unittest.TestCase):
    def test_model_uri_constructed_from_folder(self):
        client = YandexLLMClient(api_key="k", folder_id="folder123")
        self.assertEqual(client.model_uri, "gpt://folder123/yandexgpt-lite")


if __name__ == "__main__":
    unittest.main()
