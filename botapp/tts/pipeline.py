from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Awaitable, Callable

from botapp.runtime_metrics import TTSRuntimeTracker

from .base import TTSProvider, TTSProviderTimeoutError
from .chunking import (
    ChunkLimits,
    ChunkPlan,
    HierarchicalTextChunker,
    normalize_tts_text,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TTSPipelineConfig:
    chunk_plans: tuple[ChunkPlan, ...]
    retry_count: int
    per_chunk_timeout_seconds: int
    overall_timeout_seconds: int
    temp_dir: str | None = None
    cleanup_temp_files: bool = True

    @classmethod
    def from_limits(
        cls,
        *,
        max_chars_per_chunk: int,
        max_sentences_per_chunk: int,
        max_words_per_chunk: int,
        min_chars_per_chunk: int,
        retry_count: int,
        per_chunk_timeout_seconds: int,
        overall_timeout_seconds: int,
        temp_dir: str | None,
        cleanup_temp_files: bool,
    ) -> "TTSPipelineConfig":
        initial_limits = ChunkLimits(
            max_chars=max_chars_per_chunk,
            max_sentences=max_sentences_per_chunk,
            max_words=max_words_per_chunk,
            min_chars=min_chars_per_chunk,
        )
        plans = (
            ChunkPlan(
                level_name="paragraph_sentence",
                limits=initial_limits,
                separators=HierarchicalTextChunker().plans[0].separators,
            ),
            ChunkPlan(
                level_name="sentence_clause",
                limits=ChunkLimits(
                    max_chars=max(min_chars_per_chunk, max_chars_per_chunk // 2),
                    max_sentences=max(
                        1,
                        min(max_sentences_per_chunk, max_sentences_per_chunk // 2 or 1),
                    ),
                    max_words=max(
                        1, min(max_words_per_chunk, max_words_per_chunk // 2 or 1)
                    ),
                    min_chars=min_chars_per_chunk,
                ),
                separators=HierarchicalTextChunker().plans[1].separators,
            ),
            ChunkPlan(
                level_name="clause_words",
                limits=ChunkLimits(
                    max_chars=max(min_chars_per_chunk, max_chars_per_chunk // 4),
                    max_sentences=1,
                    max_words=max(
                        1, min(max_words_per_chunk, max_words_per_chunk // 4 or 1)
                    ),
                    min_chars=min_chars_per_chunk,
                ),
                separators=HierarchicalTextChunker().plans[2].separators,
            ),
            ChunkPlan(
                level_name="words",
                limits=ChunkLimits(
                    max_chars=max(min_chars_per_chunk, max_chars_per_chunk // 6),
                    max_sentences=1,
                    max_words=max(
                        1, min(max_words_per_chunk, max_words_per_chunk // 6 or 1)
                    ),
                    min_chars=min_chars_per_chunk,
                ),
                separators=(),
            ),
        )
        return cls(
            chunk_plans=plans,
            retry_count=retry_count,
            per_chunk_timeout_seconds=per_chunk_timeout_seconds,
            overall_timeout_seconds=overall_timeout_seconds,
            temp_dir=temp_dir,
            cleanup_temp_files=cleanup_temp_files,
        )

    def validate(self) -> None:
        if self.retry_count < 0:
            raise ValueError("retry_count must be >= 0")
        if self.per_chunk_timeout_seconds <= 0:
            raise ValueError("per_chunk_timeout_seconds must be > 0")
        if self.overall_timeout_seconds <= 0:
            raise ValueError("overall_timeout_seconds must be > 0")
        if not self.chunk_plans:
            raise ValueError("chunk_plans must not be empty")
        for plan in self.chunk_plans:
            plan.limits.validate()


@dataclass(frozen=True)
class TTSProgressEvent:
    stage: str
    message: str
    chunk_index: int | None = None
    chunk_total: int | None = None


class TTSPipelineError(RuntimeError):
    def __init__(
        self,
        *,
        stage: str,
        chunk_index: int | None,
        chunk_total: int | None,
        text_preview: str,
        root_exception: Exception,
    ) -> None:
        detail = getattr(
            root_exception,
            "user_message",
            f"{type(root_exception).__name__}: {root_exception}",
        )
        prefix = (
            f"Ошибка на стадии {stage}. Чанк: {chunk_index}/{chunk_total}. "
            if chunk_index and chunk_total
            else f"Ошибка на стадии {stage}. "
        )
        message = f"{prefix}Фрагмент: «{text_preview}». Причина: {detail}"
        super().__init__(message)
        self.user_message = message
        self.stage = stage
        self.chunk_index = chunk_index
        self.chunk_total = chunk_total
        self.text_preview = text_preview
        self.root_exception = root_exception


class TTSOverallTimeoutError(RuntimeError):
    def __init__(self, stage: str, timeout_seconds: int) -> None:
        super().__init__(
            "Ошибка: превышен общий лимит времени обработки аудио. "
            f"Стадия: {stage}. Таймаут: {timeout_seconds} сек."
        )
        self.user_message = str(self)
        self.stage = stage
        self.timeout_seconds = timeout_seconds


class TTSPipeline:
    def __init__(
        self,
        *,
        provider: TTSProvider,
        config: TTSPipelineConfig,
        progress_callback: Callable[[TTSProgressEvent], Awaitable[None]] | None = None,
        synth_semaphore: asyncio.Semaphore | None = None,
        runtime_tracker: TTSRuntimeTracker | None = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._config.validate()
        self._chunker = HierarchicalTextChunker(self._config.chunk_plans)
        self._progress_callback = progress_callback
        self._synth_semaphore = synth_semaphore
        self._runtime_tracker = runtime_tracker or TTSRuntimeTracker()

    async def synthesize_to_file(self, text: str, destination: Path) -> list[Path]:
        normalized_text = normalize_tts_text(text)
        deadline = time.monotonic() + self._config.overall_timeout_seconds
        job_started_at = time.monotonic()
        await self._progress("prepare_text", "Подготавливаю текст к озвучке...")
        self._check_deadline(deadline, "prepare_text")

        chunks = self._chunker.split_text(normalized_text)
        logger.info(
            "tts pipeline split completed: chars=%s chunks=%s first_plan=%s",
            len(normalized_text),
            len(chunks),
            self._chunker.plan_name(0),
        )
        await self._progress(
            "split_text",
            f"Разбиваю текст на чанки: {len(chunks)} шт.",
        )
        self._check_deadline(deadline, "split_text")
        if not chunks:
            raise ValueError("Text is empty after normalization")

        destination.parent.mkdir(parents=True, exist_ok=True)
        chunk_paths: list[Path] = []

        temp_ctx = tempfile.TemporaryDirectory(dir=self._config.temp_dir)
        try:
            work_dir = Path(temp_ctx.name)
            logger.info(
                "tts job start: destination=%s chars=%s chunks=%s metrics=%s",
                destination,
                len(normalized_text),
                len(chunks),
                self._runtime_tracker.snapshot(
                    work_dir=work_dir,
                    chunk_paths=chunk_paths,
                    started_at=job_started_at,
                ),
            )
            for chunk_index, chunk in enumerate(chunks, start=1):
                self._check_deadline(deadline, f"tts_chunk_{chunk_index}_{len(chunks)}")
                chunk_paths.extend(
                    await self._synthesize_chunk_tree(
                        text=chunk,
                        chunk_index=chunk_index,
                        chunk_total=len(chunks),
                        level_index=0,
                        work_dir=work_dir,
                        deadline=deadline,
                        chunk_paths=chunk_paths,
                        job_started_at=job_started_at,
                    )
                )

            await self._progress("merge_audio", "Собираю итоговый аудиофайл...")
            self._check_deadline(deadline, "merge_audio")
            logger.info(
                "tts before merge: destination=%s metrics=%s",
                destination,
                self._runtime_tracker.snapshot(
                    work_dir=work_dir,
                    chunk_paths=chunk_paths,
                    started_at=job_started_at,
                ),
            )
            self._merge_audio_files(chunk_paths, destination)
            logger.info(
                "tts pipeline merge completed: temp_chunks=%s destination=%s bytes=%s metrics=%s",
                len(chunk_paths),
                destination,
                destination.stat().st_size if destination.exists() else 0,
                self._runtime_tracker.snapshot(
                    work_dir=work_dir,
                    chunk_paths=chunk_paths,
                    started_at=job_started_at,
                ),
            )
            await self._progress("finalize_audio", "Финализирую аудиофайл...")
            self._check_deadline(deadline, "finalize_audio")
            logger.info(
                "tts job completed: destination=%s metrics=%s",
                destination,
                self._runtime_tracker.snapshot(
                    work_dir=work_dir,
                    chunk_paths=chunk_paths,
                    started_at=job_started_at,
                ),
            )
            return chunk_paths
        finally:
            if self._config.cleanup_temp_files:
                temp_ctx.cleanup()
            else:
                logger.info("tts pipeline temp files preserved: dir=%s", temp_ctx.name)

    async def _synthesize_chunk_tree(
        self,
        *,
        text: str,
        chunk_index: int,
        chunk_total: int,
        level_index: int,
        work_dir: Path,
        deadline: float,
        chunk_paths: list[Path],
        job_started_at: float,
    ) -> list[Path]:
        progress_stage = f"tts_chunk_{chunk_index}_{chunk_total}"
        timeout_stage = f"tts chunk {chunk_index}/{chunk_total}"
        preview = self._preview(text)

        for attempt in range(1, self._config.retry_count + 2):
            self._check_deadline(deadline, progress_stage)
            await self._progress(
                progress_stage,
                f"Синтез чанка {chunk_index}/{chunk_total} (попытка {attempt})...",
                chunk_index=chunk_index,
                chunk_total=chunk_total,
            )
            chunk_path = (
                work_dir / f"chunk_{chunk_index:04d}_{level_index}_{attempt}.mp3"
            )
            try:
                started_at = time.monotonic()
                logger.info(
                    "tts before synth: chunk=%s/%s level=%s attempt=%s chars=%s metrics=%s",
                    chunk_index,
                    chunk_total,
                    self._chunker.plan_name(level_index),
                    attempt,
                    len(text),
                    self._runtime_tracker.snapshot(
                        work_dir=work_dir,
                        chunk_paths=chunk_paths,
                        started_at=job_started_at,
                    ),
                )
                await self._run_synth(
                    text=text,
                    destination=chunk_path,
                    timeout_seconds=self._config.per_chunk_timeout_seconds,
                )
                logger.info(
                    "tts chunk completed: chunk=%s/%s level=%s attempt=%s chars=%s audio_bytes=%s duration_sec=%.3f metrics=%s",
                    chunk_index,
                    chunk_total,
                    self._chunker.plan_name(level_index),
                    attempt,
                    len(text),
                    chunk_path.stat().st_size if chunk_path.exists() else 0,
                    time.monotonic() - started_at,
                    self._runtime_tracker.snapshot(
                        work_dir=work_dir,
                        chunk_paths=chunk_paths + [chunk_path],
                        started_at=job_started_at,
                    ),
                )
                await self._progress(
                    progress_stage,
                    f"Готово: чанк {chunk_index}/{chunk_total} синтезирован.",
                    chunk_index=chunk_index,
                    chunk_total=chunk_total,
                )
                return [chunk_path]
            except TTSProviderTimeoutError as exc:
                if chunk_path.exists():
                    chunk_path.unlink()
                logger.warning(
                    "tts chunk timeout: chunk=%s/%s level=%s attempt=%s chars=%s preview=%s metrics=%s",
                    chunk_index,
                    chunk_total,
                    self._chunker.plan_name(level_index),
                    attempt,
                    len(text),
                    preview,
                    self._runtime_tracker.snapshot(
                        work_dir=work_dir,
                        chunk_paths=chunk_paths,
                        started_at=job_started_at,
                    ),
                )
                retry_chunks = self._chunker.split_for_retry(text, level_index)
                if retry_chunks:
                    logger.info(
                        "tts chunk fallback split: chunk=%s/%s from_level=%s to_level=%s parts=%s metrics=%s",
                        chunk_index,
                        chunk_total,
                        self._chunker.plan_name(level_index),
                        self._chunker.plan_name(level_index + 1),
                        len(retry_chunks),
                        self._runtime_tracker.snapshot(
                            work_dir=work_dir,
                            chunk_paths=chunk_paths,
                            started_at=job_started_at,
                        ),
                    )
                    nested_paths: list[Path] = []
                    for nested_index, nested_chunk in enumerate(retry_chunks, start=1):
                        nested_paths.extend(
                            await self._synthesize_chunk_tree(
                                text=nested_chunk,
                                chunk_index=nested_index,
                                chunk_total=len(retry_chunks),
                                level_index=level_index + 1,
                                work_dir=work_dir,
                                deadline=deadline,
                                chunk_paths=chunk_paths + nested_paths,
                                job_started_at=job_started_at,
                            )
                        )
                    return nested_paths
                raise TTSPipelineError(
                    stage=timeout_stage,
                    chunk_index=chunk_index,
                    chunk_total=chunk_total,
                    text_preview=preview,
                    root_exception=exc,
                ) from exc
            except Exception as exc:
                if chunk_path.exists():
                    chunk_path.unlink()
                logger.warning(
                    "tts chunk attempt failed: chunk=%s/%s level=%s attempt=%s chars=%s preview=%s error=%s: %s",
                    chunk_index,
                    chunk_total,
                    self._chunker.plan_name(level_index),
                    attempt,
                    len(text),
                    preview,
                    type(exc).__name__,
                    exc,
                )
                if attempt <= self._config.retry_count:
                    continue
                retry_chunks = self._chunker.split_for_retry(text, level_index)
                if retry_chunks:
                    logger.info(
                        "tts chunk fallback split: chunk=%s/%s from_level=%s to_level=%s parts=%s metrics=%s",
                        chunk_index,
                        chunk_total,
                        self._chunker.plan_name(level_index),
                        self._chunker.plan_name(level_index + 1),
                        len(retry_chunks),
                        self._runtime_tracker.snapshot(
                            work_dir=work_dir,
                            chunk_paths=chunk_paths,
                            started_at=job_started_at,
                        ),
                    )
                    nested_paths: list[Path] = []
                    for nested_index, nested_chunk in enumerate(retry_chunks, start=1):
                        nested_paths.extend(
                            await self._synthesize_chunk_tree(
                                text=nested_chunk,
                                chunk_index=nested_index,
                                chunk_total=len(retry_chunks),
                                level_index=level_index + 1,
                                work_dir=work_dir,
                                deadline=deadline,
                                chunk_paths=chunk_paths + nested_paths,
                                job_started_at=job_started_at,
                            )
                        )
                    return nested_paths
                raise TTSPipelineError(
                    stage=timeout_stage,
                    chunk_index=chunk_index,
                    chunk_total=chunk_total,
                    text_preview=preview,
                    root_exception=exc,
                ) from exc
        raise AssertionError("unreachable")

    async def _run_synth(
        self,
        *,
        text: str,
        destination: Path,
        timeout_seconds: int,
    ) -> None:
        if self._synth_semaphore is None:
            async with self._runtime_tracker.track_synth():
                await self._provider.synthesize_to_file(
                    text,
                    destination,
                    timeout_seconds=timeout_seconds,
                )
            return

        async with self._synth_semaphore:
            async with self._runtime_tracker.track_synth():
                await self._provider.synthesize_to_file(
                    text,
                    destination,
                    timeout_seconds=timeout_seconds,
                )

    def _merge_audio_files(self, chunk_paths: list[Path], destination: Path) -> None:
        if not chunk_paths:
            raise ValueError("chunk_paths must not be empty")
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            manifest = destination.parent / "ffmpeg_concat.txt"
            manifest.write_text(
                "\n".join(
                    f"file '{chunk_path.as_posix()}'" for chunk_path in chunk_paths
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(manifest),
                    "-c",
                    "copy",
                    str(destination),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return

        logger.warning("ffmpeg is not available, falling back to byte concatenation")
        with destination.open("wb") as out_file:
            for chunk_path in chunk_paths:
                with chunk_path.open("rb") as in_file:
                    shutil.copyfileobj(in_file, out_file, length=1024 * 64)

    async def _progress(
        self,
        stage: str,
        message: str,
        *,
        chunk_index: int | None = None,
        chunk_total: int | None = None,
    ) -> None:
        logger.info(
            "tts pipeline progress: stage=%s chunk=%s/%s message=%s",
            stage,
            chunk_index,
            chunk_total,
            message,
        )
        if self._progress_callback is None:
            return
        await self._progress_callback(
            TTSProgressEvent(
                stage=stage,
                message=message,
                chunk_index=chunk_index,
                chunk_total=chunk_total,
            )
        )

    def _check_deadline(self, deadline: float, stage: str) -> None:
        if time.monotonic() > deadline:
            raise TTSOverallTimeoutError(stage, self._config.overall_timeout_seconds)

    def _preview(self, text: str, limit: int = 80) -> str:
        normalized = normalize_tts_text(text)
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 1].rstrip() + "…"
