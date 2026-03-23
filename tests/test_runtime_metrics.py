from pathlib import Path
import tempfile
import unittest

from botapp.runtime_metrics import TTSRuntimeTracker, current_rss_kb, peak_rss_kb


class RuntimeMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_reports_directory_and_active_counts(self):
        tracker = TTSRuntimeTracker()
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            chunk = work_dir / "chunk.mp3"
            chunk.write_bytes(b"12345")
            async with tracker.track_job():
                async with tracker.track_synth():
                    snapshot = tracker.snapshot(work_dir=work_dir, chunk_paths=[chunk])

        self.assertEqual(snapshot.work_dir_file_count, 1)
        self.assertEqual(snapshot.work_dir_total_bytes, 5)
        self.assertEqual(snapshot.chunk_file_count, 1)
        self.assertEqual(snapshot.chunk_total_bytes, 5)
        self.assertEqual(snapshot.active_jobs, 1)
        self.assertEqual(snapshot.active_synths, 1)

    def test_rss_helpers_return_non_negative_values(self):
        self.assertGreaterEqual(current_rss_kb(), 0)
        self.assertGreaterEqual(peak_rss_kb(), 0)


if __name__ == "__main__":
    unittest.main()
