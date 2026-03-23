import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import numpy as np

from botapp.tts.base import TTSProviderTimeoutError
from botapp.tts.silero_provider import SileroTTSProvider


class _FakeTensor:
    def __init__(self, samples: np.ndarray) -> None:
        self._samples = samples

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._samples


class _FakeModel:
    def apply_tts(self, **kwargs):
        _ = kwargs
        return _FakeTensor(np.array([0.1, -0.1, 0.05], dtype=np.float32))


class _FakeEncoder:
    def __init__(self) -> None:
        self.encode_calls = 0

    def set_bit_rate(self, _value: int) -> None:
        pass

    def set_in_sample_rate(self, _value: int) -> None:
        pass

    def set_channels(self, _value: int) -> None:
        pass

    def set_quality(self, _value: int) -> None:
        pass

    def encode(self, _value: bytes) -> bytes:
        self.encode_calls += 1
        return b"x"

    def flush(self) -> bytes:
        return b"z"


class _FakeProcess:
    def __init__(self) -> None:
        self.pid = 123
        self.returncode = None
        self.killed = False
        self.wait = AsyncMock(side_effect=self._wait)

    async def communicate(self, _input: bytes):
        await asyncio.sleep(10)
        return b"", b""

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def _wait(self) -> int:
        self.returncode = -9
        return -9


class SileroProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthesize_to_file_timeout_kills_worker(self):
        provider = SileroTTSProvider()
        process = _FakeProcess()

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "botapp.tts.silero_provider.asyncio.create_subprocess_exec",
                AsyncMock(return_value=process),
            ),
        ):
            destination = Path(tmpdir) / "speech.mp3"
            with self.assertRaises(TTSProviderTimeoutError):
                await provider.synthesize_to_file(
                    "очень длинный текст",
                    destination,
                    timeout_seconds=0,
                )

        self.assertTrue(process.killed)
        process.wait.assert_awaited()
        self.assertFalse(destination.exists())


class SileroProviderMemoryTests(unittest.TestCase):
    def test_synthesize_stream_encodes_parts_without_numpy_concat(self):
        provider = SileroTTSProvider()
        provider._max_chars_per_call = 10

        text = "Первое предложение. Второе предложение. Третье предложение."
        parts = provider._split_text(text, provider._max_chars_per_call)

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "botapp.tts.silero_provider._ensure_model_loaded",
                return_value=_FakeModel(),
            ),
            patch("botapp.tts.silero_provider.lameenc.Encoder", _FakeEncoder),
            patch(
                "botapp.tts.silero_provider.np.concatenate",
                side_effect=AssertionError("np.concatenate must not be called"),
            ),
        ):
            destination = Path(tmpdir) / "speech.mp3"
            provider._synthesize_sync_to_file(text, destination)
            audio = destination.read_bytes()

        expected_encode_calls = len(parts) + max(0, len(parts) - 1)
        self.assertEqual(audio, b"x" * expected_encode_calls + b"z")


if __name__ == "__main__":
    unittest.main()
