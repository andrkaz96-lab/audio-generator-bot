import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from botapp.runtime_metrics import TTSRuntimeTracker
from botapp.tts.base import TTSProviderTimeoutError
from botapp.tts.chunking import ChunkLimits, ChunkPlan, HierarchicalTextChunker
from botapp.tts.pipeline import TTSProgressEvent, TTSPipeline, TTSPipelineConfig


class _RecordingFileProvider:
    def __init__(
        self,
        *,
        fail_above_chars: int | None = None,
        timeout_above_chars: int | None = None,
    ) -> None:
        self.fail_above_chars = fail_above_chars
        self.timeout_above_chars = timeout_above_chars
        self.calls: list[str] = []
        self.timeout_calls: list[str] = []

    async def synthesize_to_file(
        self,
        text: str,
        destination: Path,
        *,
        timeout_seconds: int | None = None,
    ) -> None:
        self.calls.append(text)
        await asyncio.sleep(0)
        if (
            self.timeout_above_chars is not None
            and len(text) > self.timeout_above_chars
        ):
            self.timeout_calls.append(text)
            raise TTSProviderTimeoutError("recording", timeout_seconds or 0)
        if self.fail_above_chars is not None and len(text) > self.fail_above_chars:
            raise RuntimeError(f"chunk too large: {len(text)}")
        destination.write_bytes(f"<{len(text)}>".encode("utf-8"))


class ChunkingTests(unittest.TestCase):
    def test_split_text_respects_limits_and_paragraphs(self):
        chunker = HierarchicalTextChunker(
            (
                ChunkPlan(
                    level_name="paragraph_sentence",
                    limits=ChunkLimits(
                        max_chars=120, max_sentences=2, max_words=20, min_chars=40
                    ),
                    separators=HierarchicalTextChunker().plans[0].separators,
                ),
                ChunkPlan(
                    level_name="sentence_clause",
                    limits=ChunkLimits(
                        max_chars=60, max_sentences=1, max_words=10, min_chars=40
                    ),
                    separators=HierarchicalTextChunker().plans[1].separators,
                ),
            )
        )
        text = (
            "Первый абзац. Второе предложение первого абзаца.\n\n"
            "Второй абзац заметно длиннее и тоже состоит из двух предложений."
            " Еще одно предложение второго абзаца."
        )

        chunks = chunker.split_text(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks))
        self.assertTrue(all(len(chunk.split()) <= 20 for chunk in chunks))

    def test_split_for_retry_creates_smaller_chunks(self):
        chunker = HierarchicalTextChunker(
            (
                ChunkPlan(
                    level_name="paragraph_sentence",
                    limits=ChunkLimits(
                        max_chars=120, max_sentences=3, max_words=30, min_chars=40
                    ),
                    separators=HierarchicalTextChunker().plans[0].separators,
                ),
                ChunkPlan(
                    level_name="sentence_clause",
                    limits=ChunkLimits(
                        max_chars=60, max_sentences=1, max_words=10, min_chars=40
                    ),
                    separators=HierarchicalTextChunker().plans[1].separators,
                ),
                ChunkPlan(
                    level_name="words",
                    limits=ChunkLimits(
                        max_chars=40, max_sentences=1, max_words=6, min_chars=20
                    ),
                    separators=(),
                ),
            )
        )
        text = (
            "Очень длинное предложение с несколькими частями, которое должно дробиться "
            "сначала по предложениям, а затем при повторной ошибке еще и по словам."
        )

        initial = chunker.split_text(text)
        fallback = chunker.split_for_retry(initial[0], 0)

        self.assertGreater(len(fallback), 1)
        self.assertTrue(max(len(chunk) for chunk in fallback) < len(initial[0]))


class TTSPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_falls_back_to_smaller_chunks_after_failure(self):
        provider = _RecordingFileProvider(fail_above_chars=80)
        config = TTSPipelineConfig.from_limits(
            max_chars_per_chunk=120,
            max_sentences_per_chunk=3,
            max_words_per_chunk=30,
            min_chars_per_chunk=40,
            retry_count=0,
            per_chunk_timeout_seconds=5,
            overall_timeout_seconds=30,
            temp_dir=None,
            cleanup_temp_files=True,
        )
        progress: list[TTSProgressEvent] = []
        pipeline = TTSPipeline(
            provider=provider,
            config=config,
            progress_callback=lambda event: self._collect_progress(progress, event),
        )
        text = (
            "Очень длинное предложение с несколькими частями, которое не помещается в безопасный лимит, "
            "поэтому после первой ошибки должно быть разбито на более мелкие куски."
        )

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("botapp.tts.pipeline.shutil.which", return_value=None),
        ):
            destination = Path(tmpdir) / "speech.mp3"
            chunk_paths = await pipeline.synthesize_to_file(text, destination)

            self.assertTrue(destination.exists())
            self.assertGreater(len(chunk_paths), 1)
            self.assertGreater(len(provider.calls), len(chunk_paths))
            self.assertTrue(any(len(call) > 80 for call in provider.calls))
            self.assertTrue(all(len(call) <= 80 for call in provider.calls[1:]))
            self.assertIn("split_text", [event.stage for event in progress])
            self.assertTrue(
                any(event.stage.startswith("tts_chunk_") for event in progress)
            )

    async def test_pipeline_uses_file_based_provider_api(self):
        provider = _RecordingFileProvider()
        config = TTSPipelineConfig.from_limits(
            max_chars_per_chunk=80,
            max_sentences_per_chunk=2,
            max_words_per_chunk=20,
            min_chars_per_chunk=20,
            retry_count=0,
            per_chunk_timeout_seconds=5,
            overall_timeout_seconds=30,
            temp_dir=None,
            cleanup_temp_files=True,
        )
        pipeline = TTSPipeline(provider=provider, config=config)

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("botapp.tts.pipeline.shutil.which", return_value=None),
        ):
            destination = Path(tmpdir) / "speech.mp3"
            chunk_paths = await pipeline.synthesize_to_file(
                "Короткий текст для синтеза.", destination
            )

            self.assertTrue(destination.exists())
            self.assertGreater(destination.stat().st_size, 0)
            self.assertEqual(len(chunk_paths), 1)

    async def test_timeout_skips_same_size_retry_and_splits_immediately(self):
        provider = _RecordingFileProvider(timeout_above_chars=80)
        config = TTSPipelineConfig.from_limits(
            max_chars_per_chunk=120,
            max_sentences_per_chunk=3,
            max_words_per_chunk=30,
            min_chars_per_chunk=40,
            retry_count=3,
            per_chunk_timeout_seconds=1,
            overall_timeout_seconds=30,
            temp_dir=None,
            cleanup_temp_files=True,
        )
        pipeline = TTSPipeline(provider=provider, config=config)
        text = (
            "Очень длинное предложение с несколькими частями, которое должно сначала словить таймаут, "
            "а затем быть немедленно разбито на более короткие чанки без same-size retry."
        )

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("botapp.tts.pipeline.shutil.which", return_value=None),
        ):
            destination = Path(tmpdir) / "speech.mp3"
            chunk_paths = await pipeline.synthesize_to_file(text, destination)

            self.assertTrue(destination.exists())
            self.assertGreater(len(chunk_paths), 1)
            long_calls = [call for call in provider.calls if len(call) > 80]
            self.assertEqual(len(long_calls), 1)
            self.assertEqual(provider.timeout_calls, long_calls)

    async def test_pipeline_handles_stress_text_without_single_giant_chunk(self):
        sample = (
            "Каждый четвертый предприниматель совмещает работу ПВЗ с другим бизнесом в том же помещении. "
            "Треть владельцев ПВЗ заинтересованы в запуске дополнительного бизнеса в ПВЗ или планируют "
            "его в ближайшее время."
        )
        text = " ".join([sample] * 500)
        provider = _RecordingFileProvider()
        config = TTSPipelineConfig.from_limits(
            max_chars_per_chunk=180,
            max_sentences_per_chunk=2,
            max_words_per_chunk=35,
            min_chars_per_chunk=60,
            retry_count=0,
            per_chunk_timeout_seconds=5,
            overall_timeout_seconds=60,
            temp_dir=None,
            cleanup_temp_files=True,
        )
        progress: list[TTSProgressEvent] = []
        pipeline = TTSPipeline(
            provider=provider,
            config=config,
            progress_callback=lambda event: self._collect_progress(progress, event),
            runtime_tracker=TTSRuntimeTracker(),
        )

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch("botapp.tts.pipeline.shutil.which", return_value=None),
        ):
            destination = Path(tmpdir) / "stress.mp3"
            await pipeline.synthesize_to_file(text, destination)

            self.assertTrue(destination.exists())
            self.assertGreater(len(provider.calls), 50)
            self.assertTrue(all(len(call) <= 180 for call in provider.calls))
            self.assertGreater(destination.stat().st_size, 0)
            completed_chunk_events = [
                event for event in progress if event.message.startswith("Готово: чанк")
            ]
            self.assertEqual(len(completed_chunk_events), len(provider.calls))

    async def _collect_progress(
        self,
        progress: list[TTSProgressEvent],
        event: TTSProgressEvent,
    ) -> None:
        progress.append(event)


if __name__ == "__main__":
    unittest.main()
