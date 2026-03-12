import unittest
from unittest.mock import patch

from botapp.llm.yandex_client import YandexLLMClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class RecordingAsyncClient:
    def __init__(self, responses, calls, payloads):
        self.responses = responses
        self.calls = calls
        self.payloads = payloads

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *args, **kwargs):
        self.calls.append(url)
        self.payloads.append(kwargs.get("json") or {})
        return self.responses.pop(0)


class YandexEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_openai_compatible_endpoint_and_payload(self):
        calls: list[str] = []
        payloads: list[dict] = []
        responses = [FakeResponse(status_code=200, payload={"choices": [{"message": {"content": "ok"}}]})]

        with patch("httpx.AsyncClient", side_effect=lambda *a, **k: RecordingAsyncClient(responses, calls, payloads)):
            client = YandexLLMClient(api_key="k", folder_id="b1geq9r8nerbilj0i53p", api_base="https://llm.api.cloud.yandex.net/v1")
            result = await client.normalize_article(title="t", body_text="b", source_url="u")

        self.assertTrue(result.success)
        self.assertEqual(calls[0], "https://llm.api.cloud.yandex.net/v1/chat/completions")
        self.assertEqual(payloads[0]["model"], "gpt://b1geq9r8nerbilj0i53p/yandexgpt-lite")
        self.assertIn("messages", payloads[0])


if __name__ == "__main__":
    unittest.main()
