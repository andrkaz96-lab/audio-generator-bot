from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
import resource
from time import monotonic


@dataclass(frozen=True)
class DirectoryUsage:
    file_count: int
    total_bytes: int


@dataclass(frozen=True)
class RuntimeSnapshot:
    current_rss_kb: int
    peak_rss_kb: int
    work_dir_file_count: int
    work_dir_total_bytes: int
    chunk_file_count: int
    chunk_total_bytes: int
    active_jobs: int
    active_synths: int
    elapsed_ms: int | None = None


class TTSRuntimeTracker:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_jobs = 0
        self._active_synths = 0

    @property
    def active_jobs(self) -> int:
        return self._active_jobs

    @property
    def active_synths(self) -> int:
        return self._active_synths

    @asynccontextmanager
    async def track_job(self):
        async with self._lock:
            self._active_jobs += 1
        try:
            yield
        finally:
            async with self._lock:
                self._active_jobs -= 1

    @asynccontextmanager
    async def track_synth(self):
        async with self._lock:
            self._active_synths += 1
        try:
            yield
        finally:
            async with self._lock:
                self._active_synths -= 1

    def snapshot(
        self,
        *,
        work_dir: Path | None = None,
        chunk_paths: list[Path] | None = None,
        started_at: float | None = None,
    ) -> RuntimeSnapshot:
        work_usage = get_directory_usage(work_dir)
        chunk_usage = get_paths_usage(chunk_paths or [])
        elapsed_ms = None
        if started_at is not None:
            elapsed_ms = int((monotonic() - started_at) * 1000)
        return RuntimeSnapshot(
            current_rss_kb=current_rss_kb(),
            peak_rss_kb=peak_rss_kb(),
            work_dir_file_count=work_usage.file_count,
            work_dir_total_bytes=work_usage.total_bytes,
            chunk_file_count=chunk_usage.file_count,
            chunk_total_bytes=chunk_usage.total_bytes,
            active_jobs=self._active_jobs,
            active_synths=self._active_synths,
            elapsed_ms=elapsed_ms,
        )


def current_rss_kb() -> int:
    status_path = Path("/proc/self/status")
    if status_path.exists():
        for line in status_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1])
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return int(usage.ru_maxrss)


def peak_rss_kb() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return int(usage.ru_maxrss)


def get_directory_usage(directory: Path | None) -> DirectoryUsage:
    if directory is None or not directory.exists():
        return DirectoryUsage(file_count=0, total_bytes=0)

    file_count = 0
    total_bytes = 0
    for path in directory.rglob("*"):
        if path.is_file():
            file_count += 1
            total_bytes += path.stat().st_size
    return DirectoryUsage(file_count=file_count, total_bytes=total_bytes)


def get_paths_usage(paths: list[Path]) -> DirectoryUsage:
    existing = [path for path in paths if path.exists()]
    return DirectoryUsage(
        file_count=len(existing),
        total_bytes=sum(path.stat().st_size for path in existing),
    )
