import unittest
from unittest.mock import patch

import httpx

from botapp.llm.yandex_client import YandexLLMClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class YandexClientRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_on_429(self):
        responses = [
            FakeResponse(status_code=429),
            FakeResponse(status_code=200, payload={"choices": [{"message": {"content": "A"}}]}),
        ]
        with patch("httpx.AsyncClient", side_effect=lambda *a, **k: FakeAsyncClient(responses)):
            client = YandexLLMClient(api_key="k", folder_id="f")
            result = await client.normalize_article(title="t", body_text="b", source_url="u")
            self.assertTrue(result.success)
            self.assertEqual(result.retry_count, 1)

    async def test_no_retry_on_400(self):
        responses = [FakeResponse(status_code=400)]
        with patch("httpx.AsyncClient", side_effect=lambda *a, **k: FakeAsyncClient(responses)):
            client = YandexLLMClient(api_key="k", folder_id="f")
            result = await client.normalize_article(title="t", body_text="b", source_url="u")
            self.assertFalse(result.success)
            self.assertEqual(result.retry_count, 0)
            self.assertEqual(result.error_type, "HTTP_400")


if __name__ == "__main__":
    unittest.main()
