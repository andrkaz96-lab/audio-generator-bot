from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Optional

import lameenc
import numpy as np
import torch

from .base import TTSProvider, TTSProviderTimeoutError, TTSProviderUnavailableError


logger = logging.getLogger(__name__)
_MODEL: Optional[torch.nn.Module] = None


class SileroTTSProvider(TTSProvider):
    def __init__(
        self,
        speaker: str = "xenia",
        sample_rate: int = 48000,
        model_language: str = "ru",
        model_speaker: str = "v4_ru",
        repo_dir: str | None = None,
        allow_download_on_startup: bool = True,
        worker_python_executable: str | None = None,
    ) -> None:
        self._speaker = speaker
        self._sample_rate = sample_rate
        self._model_language = model_language
        self._model_speaker = model_speaker
        self._max_chars_per_call = 900
        self._repo_dir = (
            Path(repo_dir).expanduser()
            if repo_dir
            else Path.home() / ".cache" / "audio-generator-bot" / "silero-models"
        )
        self._allow_download_on_startup = allow_download_on_startup
        self._worker_python_executable = worker_python_executable or sys.executable

    @property
    def is_local(self) -> bool:
        return True

    async def preload(self) -> None:
        await asyncio.to_thread(self._ensure_repo_available)

    async def reset(self) -> None:
        return None

    async def synthesize_to_file(
        self,
        text: str,
        destination: Path,
        *,
        timeout_seconds: int | None = None,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self._worker_python_executable,
            "-m",
            "botapp.tts.silero_provider",
            "--output",
            str(destination),
            "--speaker",
            self._speaker,
            "--sample-rate",
            str(self._sample_rate),
            "--model-language",
            self._model_language,
            "--model-speaker",
            self._model_speaker,
            "--repo-dir",
            str(self._repo_dir),
            "--max-chars-per-call",
            str(self._max_chars_per_call),
        ]
        if self._allow_download_on_startup:
            command.append("--allow-download")

        logger.info(
            "silero subprocess synth started: chars=%s destination=%s timeout=%s",
            len(text),
            destination,
            timeout_seconds,
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(text.encode("utf-8")),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            await self._terminate_process(process)
            if destination.exists():
                destination.unlink()
            raise TTSProviderTimeoutError(
                self.provider_name, timeout_seconds or 0
            ) from exc
        except asyncio.CancelledError:
            await self._terminate_process(process)
            if destination.exists():
                destination.unlink()
            raise

        if process.returncode != 0:
            if destination.exists():
                destination.unlink()
            error_message = (
                stderr.decode("utf-8", errors="ignore").strip()
                or stdout.decode("utf-8", errors="ignore").strip()
                or f"Silero worker exited with code {process.returncode}"
            )
            raise TTSProviderUnavailableError(self.provider_name, error_message)

    async def _terminate_process(
        self, process: asyncio.subprocess.Process, *, grace_seconds: float = 2.0
    ) -> None:
        if process.returncode is not None:
            return
        process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=grace_seconds)
        except asyncio.TimeoutError:
            logger.error("silero worker did not exit after SIGKILL")
        logger.warning("silero subprocess killed: pid=%s", process.pid)

    def _ensure_repo_available(self) -> None:
        repo_exists = (self._repo_dir / "src").exists()
        logger.info(
            "Silero preload started",
            extra={
                "provider_name": self.provider_name,
                "model_source": "local_cache" if repo_exists else "download",
                "repo_dir": str(self._repo_dir),
                "preload_phase": True,
            },
        )
        if not repo_exists:
            if not self._allow_download_on_startup:
                raise RuntimeError(
                    f"Silero repository is missing at {self._repo_dir} and SILERO_ALLOW_DOWNLOAD_ON_STARTUP=false"
                )
            self._clone_silero_repo()
        logger.info(
            "Silero preload finished",
            extra={
                "provider_name": self.provider_name,
                "model_source": "local_cache" if repo_exists else "download",
                "preload_success": True,
                "repo_dir": str(self._repo_dir),
            },
        )

    def _clone_silero_repo(self) -> None:
        self._repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "https://github.com/snakers4/silero-models.git",
                str(self._repo_dir),
            ],
            check=True,
        )

    def _synthesize_sync_to_file(self, text: str, destination: Path) -> None:
        model = _ensure_model_loaded(
            repo_dir=self._repo_dir,
            model_language=self._model_language,
            model_speaker=self._model_speaker,
            allow_download_on_startup=self._allow_download_on_startup,
        )
        parts = self._split_text(text, self._max_chars_per_call)
        started_at = time.monotonic()

        encoder = lameenc.Encoder()
        encoder.set_bit_rate(128)
        encoder.set_in_sample_rate(self._sample_rate)
        encoder.set_channels(1)
        encoder.set_quality(2)

        pause_pcm16 = self._pcm16(
            np.zeros(int(self._sample_rate * 0.12), dtype=np.float32)
        )

        logger.info(
            "silero tts synth started: chars=%s parts=%s destination=%s",
            len(text),
            len(parts),
            destination,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as output:
            if not parts:
                output.write(encoder.flush())
                return

            for idx, part in enumerate(parts, start=1):
                part_started_at = time.monotonic()
                audio = model.apply_tts(
                    text=part,
                    speaker=self._speaker,
                    sample_rate=self._sample_rate,
                    put_accent=True,
                    put_yo=True,
                )
                output.write(encoder.encode(self._pcm16(audio.detach().cpu().numpy())))
                if idx < len(parts):
                    output.write(encoder.encode(pause_pcm16))

                logger.info(
                    "silero tts part completed: part=%s/%s chars=%s duration_sec=%.3f",
                    idx,
                    len(parts),
                    len(part),
                    time.monotonic() - part_started_at,
                )
            output.write(encoder.flush())
        logger.info(
            "silero tts synth completed: chars=%s parts=%s duration_sec=%.3f output_bytes=%s",
            len(text),
            len(parts),
            time.monotonic() - started_at,
            destination.stat().st_size if destination.exists() else 0,
        )

    def _pcm16(self, samples: np.ndarray) -> bytes:
        clipped = np.clip(samples, -1.0, 1.0)
        return (clipped * 32767.0).astype(np.int16).tobytes()

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


def _ensure_model_loaded(
    *,
    repo_dir: Path,
    model_language: str,
    model_speaker: str,
    allow_download_on_startup: bool,
):
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    repo_exists = (repo_dir / "src").exists()
    if not repo_exists:
        if not allow_download_on_startup:
            raise RuntimeError(
                f"Silero repository is missing at {repo_dir} and SILERO_ALLOW_DOWNLOAD_ON_STARTUP=false"
            )
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "https://github.com/snakers4/silero-models.git",
                str(repo_dir),
            ],
            check=True,
        )
    model, _ = torch.hub.load(
        repo_or_dir=str(repo_dir),
        model="silero_tts",
        language=model_language,
        speaker=model_speaker,
        source="local",
    )
    model.to("cpu")
    _MODEL = model
    return model


def _run_worker(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO)
    provider = SileroTTSProvider(
        speaker=args.speaker,
        sample_rate=args.sample_rate,
        model_language=args.model_language,
        model_speaker=args.model_speaker,
        repo_dir=args.repo_dir,
        allow_download_on_startup=args.allow_download,
    )
    provider._max_chars_per_call = args.max_chars_per_call
    text = sys.stdin.read()
    if not text.strip():
        raise RuntimeError("Silero worker received empty text")
    provider._synthesize_sync_to_file(text, Path(args.output))
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--speaker", default="xenia")
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--model-language", default="ru")
    parser.add_argument("--model-speaker", default="v4_ru")
    parser.add_argument("--repo-dir", required=True)
    parser.add_argument("--max-chars-per-call", type=int, default=900)
    parser.add_argument("--allow-download", action="store_true")
    return parser


if __name__ == "__main__":
    try:
        raise SystemExit(_run_worker(_build_arg_parser().parse_args()))
    except Exception as exc:
        logging.basicConfig(level=logging.INFO)
        logging.exception("Silero worker failed: %s", exc)
        if "--output" in sys.argv:
            output_index = sys.argv.index("--output") + 1
            if output_index < len(sys.argv):
                output_path = Path(sys.argv[output_index])
                if output_path.exists():
                    output_path.unlink()
        raise
