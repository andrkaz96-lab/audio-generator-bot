from pathlib import Path
import tempfile
import unittest

from botapp.tts.base import TTSProviderTimeoutError
from botapp.tts.fallback_provider import FallbackTTSProvider


class _Provider:
    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self.calls = 0
        self.reset_calls = 0

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__

    @property
    def is_local(self) -> bool:
        return True

    async def preload(self) -> None:
        return None

    async def reset(self) -> None:
        self.reset_calls += 1

    async def synthesize_to_file(
        self, text: str, destination: Path, *, timeout_seconds: int | None = None
    ) -> None:
        _ = text, timeout_seconds
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        destination.write_bytes(b"fallback")


class FallbackProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_primary_switches_to_fallback_and_resets_primary(self):
        primary = _Provider(fail_with=TTSProviderTimeoutError("silero", 1))
        fallback = _Provider()
        provider = FallbackTTSProvider(primary=primary, fallback=fallback)

        with tempfile.TemporaryDirectory() as tmpdir:
            destination = Path(tmpdir) / "speech.mp3"
            await provider.synthesize_to_file("text", destination, timeout_seconds=1)
            self.assertEqual(destination.read_bytes(), b"fallback")

        self.assertEqual(primary.calls, 1)
        self.assertEqual(primary.reset_calls, 1)
        self.assertEqual(fallback.calls, 1)

    async def test_after_timeout_remaining_calls_use_fallback_only(self):
        primary = _Provider(fail_with=TTSProviderTimeoutError("silero", 1))
        fallback = _Provider()
        provider = FallbackTTSProvider(primary=primary, fallback=fallback)

        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "first.mp3"
            second = Path(tmpdir) / "second.mp3"
            await provider.synthesize_to_file("text", first, timeout_seconds=1)
            await provider.synthesize_to_file("text", second, timeout_seconds=1)

        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 2)


if __name__ == "__main__":
    unittest.main()
