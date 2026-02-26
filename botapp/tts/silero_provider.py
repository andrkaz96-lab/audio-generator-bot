from __future__ import annotations

import asyncio
import re
from typing import Optional

import lameenc
import numpy as np
import torch

from .base import TTSProvider


class SileroTTSProvider(TTSProvider):
    def __init__(
        self,
        speaker: str = "xenia",
        sample_rate: int = 48000,
        model_language: str = "ru",
        model_speaker: str = "v4_ru",
    ) -> None:
        self._speaker = speaker
        self._sample_rate = sample_rate
        self._model_language = model_language
        self._model_speaker = model_speaker
        self._model: Optional[torch.nn.Module] = None
        self._max_chars_per_call = 900

    async def synthesize(self, text: str) -> bytes:
        return await asyncio.to_thread(self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> bytes:
        model = self._ensure_model_loaded()
        parts = self._split_text(text, self._max_chars_per_call)
        audio_chunks: list[np.ndarray] = []

        for part in parts:
            audio = model.apply_tts(
                text=part,
                speaker=self._speaker,
                sample_rate=self._sample_rate,
                put_accent=True,
                put_yo=True,
            )
            audio_chunks.append(audio.detach().cpu().numpy())

        if not audio_chunks:
            return self._encode_mp3(np.array([], dtype=np.float32))

        # Small pause between parts so speech sounds natural after splitting.
        pause = np.zeros(int(self._sample_rate * 0.12), dtype=np.float32)
        merged: list[np.ndarray] = []
        for idx, chunk in enumerate(audio_chunks):
            merged.append(chunk)
            if idx < len(audio_chunks) - 1:
                merged.append(pause)

        samples = np.concatenate(merged)
        return self._encode_mp3(samples)

    def _ensure_model_loaded(self):
        if self._model is not None:
            return self._model

        model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-models",
            model="silero_tts",
            language=self._model_language,
            speaker=self._model_speaker,
        )
        model.to("cpu")
        self._model = model
        return model

    def _encode_mp3(self, samples: np.ndarray) -> bytes:
        clipped = np.clip(samples, -1.0, 1.0)
        pcm16 = (clipped * 32767.0).astype(np.int16).tobytes()

        encoder = lameenc.Encoder()
        encoder.set_bit_rate(128)
        encoder.set_in_sample_rate(self._sample_rate)
        encoder.set_channels(1)
        encoder.set_quality(2)

        return encoder.encode(pcm16) + encoder.flush()

    def _split_text(self, text: str, max_chars: int) -> list[str]:
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            return []
        if len(cleaned) <= max_chars:
            return [cleaned]

        sentences = re.split(r"(?<=[.!?…])\s+", cleaned)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= max_chars:
                current = candidate
                continue

            if current:
                chunks.append(current)
                current = ""

            if len(sentence) <= max_chars:
                current = sentence
            else:
                for i in range(0, len(sentence), max_chars):
                    chunks.append(sentence[i : i + max_chars])

        if current:
            chunks.append(current)
        return chunks
