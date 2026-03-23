import asyncio
from pathlib import Path
import tempfile
import unittest

from botapp.runtime_metrics import TTSRuntimeTracker
from botapp.tts.pipeline import TTSPipeline, TTSPipelineConfig


class _BlockingProvider:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self._release = asyncio.Event()
        self._started = asyncio.Event()

    async def synthesize_to_file(
        self, text: str, destination: Path, *, timeout_seconds: int | None = None
    ) -> None:
        _ = text, timeout_seconds
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self._started.set()
        await self._release.wait()
        destination.write_bytes(b"ok")
        self.active -= 1

    async def wait_started(self) -> None:
        await self._started.wait()

    def release(self) -> None:
        self._release.set()


class TTSConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_synth_semaphore_limits_parallel_chunks(self):
        provider = _BlockingProvider()
        config = TTSPipelineConfig.from_limits(
            max_chars_per_chunk=200,
            max_sentences_per_chunk=2,
            max_words_per_chunk=35,
            min_chars_per_chunk=20,
            retry_count=0,
            per_chunk_timeout_seconds=5,
            overall_timeout_seconds=30,
            temp_dir=None,
            cleanup_temp_files=True,
        )
        semaphore = asyncio.Semaphore(1)
        pipeline1 = TTSPipeline(
            provider=provider,
            config=config,
            synth_semaphore=semaphore,
            runtime_tracker=TTSRuntimeTracker(),
        )
        pipeline2 = TTSPipeline(
            provider=provider,
            config=config,
            synth_semaphore=semaphore,
            runtime_tracker=TTSRuntimeTracker(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            task1 = asyncio.create_task(
                pipeline1.synthesize_to_file("Первый текст.", Path(tmpdir) / "one.mp3")
            )
            await provider.wait_started()
            task2 = asyncio.create_task(
                pipeline2.synthesize_to_file("Второй текст.", Path(tmpdir) / "two.mp3")
            )
            await asyncio.sleep(0.05)
            self.assertEqual(provider.max_active, 1)
            provider.release()
            await asyncio.gather(task1, task2)

        self.assertEqual(provider.max_active, 1)


if __name__ == "__main__":
    unittest.main()
