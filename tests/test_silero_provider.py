import unittest
from unittest.mock import patch

import numpy as np

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


class SileroProviderMemoryTests(unittest.TestCase):
    def test_synthesize_stream_encodes_parts_without_numpy_concat(self):
        provider = SileroTTSProvider()
        provider._model = _FakeModel()
        provider._max_chars_per_call = 10

        text = "Первое предложение. Второе предложение. Третье предложение."
        parts = provider._split_text(text, provider._max_chars_per_call)

        with (
            patch("botapp.tts.silero_provider.lameenc.Encoder", _FakeEncoder),
            patch(
                "botapp.tts.silero_provider.np.concatenate",
                side_effect=AssertionError("np.concatenate must not be called"),
            ),
        ):
            audio = provider._synthesize_sync(text)

        expected_encode_calls = len(parts) + max(0, len(parts) - 1)
        self.assertEqual(audio, b"x" * expected_encode_calls + b"z")


if __name__ == "__main__":
    unittest.main()
