import unittest

from botapp.llm.prompts import (
    MODE_AUDIO_ADAPTED,
    MODE_AUDIO_SUMMARY,
    MODE_CLOSE_TO_SOURCE,
    PromptContext,
    build_user_prompt,
    canonical_mode,
)
from botapp.llm.service import ArticleLLMService
from botapp.llm.yandex_client import LLMCallResult, YandexLLMClient


class DummyClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.model_uri = "gpt://folder/yandexgpt-lite"

    async def normalize_article(
        self, *, title, body_text, source_url, mode="near_verbatim"
    ):
        self.calls.append((title, body_text, source_url, mode))
        return self.results.pop(0)

    async def complete(
        self, *, system_prompt, user_prompt, input_chars, max_tokens=7000
    ):
        self.calls.append((system_prompt, user_prompt, input_chars, max_tokens))
        return self.results.pop(0)


class ArticleLLMServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_when_llm_fails(self):
        client = DummyClient(
            [
                LLMCallResult(
                    "",
                    "yandex",
                    "gpt://folder/yandexgpt-lite",
                    False,
                    "HTTP_500",
                    100,
                    10,
                    0,
                    10,
                    0,
                    10,
                    "local_heuristic",
                    2,
                )
            ]
        )
        service = ArticleLLMService(
            enabled=True,
            provider="yandex",
            model="yandexgpt-lite/latest",
            max_input_chars=18000,
            log_prompts=False,
            client=client,
        )
        result = await service.build_tts_text_for_article(
            title="Заголовок", body_text="Тело", source_url="https://a.b"
        )
        self.assertTrue(result.used_fallback)
        self.assertEqual(result.final_text, "Заголовок\n\nТело")

    async def test_verifier_pass_repair_fail(self):
        pass_json = LLMCallResult(
            '{"decision":"pass","notes":"ok","repaired_text":""}',
            "yandex",
            "u",
            True,
            None,
            1,
            1,
            1,
            1,
            1,
            2,
            "local_heuristic",
            0,
        )
        repair_json = LLMCallResult(
            '{"decision":"repair","notes":"trimmed","repaired_text":"Заголовок\\n\\nТекст 10"}',
            "yandex",
            "u",
            True,
            None,
            1,
            1,
            1,
            1,
            1,
            2,
            "local_heuristic",
            0,
        )
        fail_json = LLMCallResult(
            "not-json",
            "yandex",
            "u",
            True,
            None,
            1,
            1,
            1,
            1,
            1,
            2,
            "local_heuristic",
            0,
        )
        client = DummyClient([pass_json, repair_json, fail_json])
        service = ArticleLLMService(
            enabled=True,
            provider="yandex",
            model="m",
            max_input_chars=1000,
            log_prompts=False,
            client=client,
        )

        p = await service.verify_and_repair(
            source_title="Заголовок",
            source_body="Текст 10",
            draft_text="Текст 10",
            mode=MODE_AUDIO_ADAPTED,
        )
        r = await service.verify_and_repair(
            source_title="Заголовок",
            source_body="Текст 10",
            draft_text="Текст 20",
            mode=MODE_AUDIO_SUMMARY,
        )
        f = await service.verify_and_repair(
            source_title="Заголовок",
            source_body="Текст 10",
            draft_text="Текст 20",
            mode=MODE_AUDIO_SUMMARY,
        )

        self.assertEqual(p.status, "pass")
        self.assertEqual(r.status, "repaired")
        self.assertEqual(f.status, "failed")


class PromptTests(unittest.TestCase):
    def test_mode_aliases_and_prompt_context(self):
        self.assertEqual(canonical_mode("near_verbatim"), MODE_CLOSE_TO_SOURCE)
        self.assertEqual(canonical_mode("readable_cleaned"), MODE_AUDIO_ADAPTED)
        prompt = build_user_prompt(
            context=PromptContext(
                mode=MODE_AUDIO_SUMMARY,
                source_url="https://example.com",
                title="T",
                body_text="B",
                target_duration_sec=120,
                hard_cap_sec=180,
                word_budget=350,
            )
        )
        self.assertIn("Жесткий лимит", prompt)


class YandexClientModelUriTests(unittest.TestCase):
    def test_model_uri_constructed_from_folder(self):
        client = YandexLLMClient(api_key="k", folder_id="folder123")
        self.assertEqual(client.model_uri, "gpt://folder123/yandexgpt-lite")


if __name__ == "__main__":
    unittest.main()
