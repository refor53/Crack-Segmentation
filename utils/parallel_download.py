"""Resume a contiguous .part file using a bounded number of HTTP Range requests."""

import concurrent.futures
import os
import threading
import time
import urllib.request
from pathlib import Path


def download_parallel(url: str, partial: Path, size: int, connections: int) -> None:
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > size:
        raise RuntimeError(f"Partial file exceeds expected size: {partial}")
    if offset == size:
        partial.touch(exist_ok=True)
        return
    chunks = partial.with_name(partial.name + ".chunks")
    chunks.mkdir(exist_ok=True)
    stop = threading.Event()
    chunk_size = 8 * 1024 * 1024

    def fetch(start: int, end: int) -> Path:
        ready = chunks / f"{start}-{end}.ready"
        temporary = chunks / f"{start}-{end}.tmp"
        if ready.exists() and ready.stat().st_size == end - start + 1:
            return ready
        for attempt in range(3):
            if stop.is_set():
                raise RuntimeError("Download stopped")
            try:
                request = urllib.request.Request(
                    url, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    expected = f"bytes {start}-{end}/{size}"
                    if response.status != 206 or response.headers.get("Content-Range") != expected:
                        raise RuntimeError(f"Server did not honor byte range {expected}")
                    received = 0
                    with temporary.open("wb") as output:
                        while received < end - start + 1:
                            if stop.is_set():
                                raise RuntimeError("Download stopped")
                            block = response.read(min(256 * 1024, end - start + 1 - received))
                            if not block:
                                raise RuntimeError("Incomplete range response")
                            output.write(block)
                            received += len(block)
                temporary.replace(ready)
                return ready
            except Exception:
                if attempt == 2 or stop.is_set():
                    raise
                if stop.wait(2 ** attempt):
                    raise RuntimeError("Download stopped")
        raise RuntimeError("Download failed")

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=connections)
    pending = {}
    next_request = offset
    started = time.monotonic()
    original_offset = offset
    last_report = started
    try:
        with partial.open("ab") as output:
            while offset < size:
                while len(pending) < connections and next_request < size:
                    end = min(next_request + chunk_size, size) - 1
                    pending[next_request] = (end, pool.submit(fetch, next_request, end))
                    next_request = end + 1
                end, future = pending[offset]
                done, _ = concurrent.futures.wait([future], timeout=1)
                if not done:
                    now = time.monotonic()
                    if now - last_report >= 15:
                        speed = (offset - original_offset) / (now - started)
                        print(f"{partial.name}: {offset / size:.1%}, committed {speed / 1e6:.2f} MB/s", flush=True)
                        last_report = now
                    continue
                ready = future.result()
                with ready.open("rb") as source:
                    while block := source.read(1024 * 1024):
                        output.write(block)
                output.flush()
                os.fsync(output.fileno())
                del pending[offset]
                offset = end + 1
                ready.unlink()
                speed = (offset - original_offset) / (time.monotonic() - started)
                remaining = (size - offset) / speed if speed else 0
                print(f"{partial.name}: {offset / size:.1%}, {speed / 1e6:.2f} MB/s, ETA {remaining / 60:.1f} min", flush=True)
    finally:
        stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
