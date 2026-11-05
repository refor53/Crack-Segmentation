"""Check persisted resume state using a local HTTP Range server."""

import http.server
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from parallel_download import download_parallel


class ResumeTests(unittest.TestCase):
    def test_resume_uses_existing_prefix_and_completed_chunk(self):
        data = bytes(range(256)) * (96 * 1024)
        requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                start, end = map(int, self.headers["Range"].removeprefix("bytes=").split("-"))
                requests.append((start, end))
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                self.wfile.write(data[start:end + 1])

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                partial = Path(temporary) / "file.part"
                prefix = 12345
                partial.write_bytes(data[:prefix])
                chunks = partial.with_name(partial.name + ".chunks")
                chunks.mkdir()
                end = prefix + 8 * 1024 * 1024 - 1
                (chunks / f"{prefix}-{end}.ready").write_bytes(data[prefix:end + 1])
                download_parallel(f"http://127.0.0.1:{server.server_port}/file", partial, len(data), 4)
                self.assertEqual(partial.read_bytes(), data)
                self.assertNotIn((prefix, end), requests)
                self.assertTrue(all(start > end for start, _ in requests))
                self.assertFalse(list(chunks.glob("*.ready")))
        finally:
            server.shutdown()
            server.server_close()

    def test_network_timeout_exits_instead_of_waiting_forever(self):
        code = '''
import tempfile
from pathlib import Path
from unittest.mock import patch
from parallel_download import download_parallel
with tempfile.TemporaryDirectory() as folder:
    with patch("urllib.request.urlopen", side_effect=TimeoutError("simulated timeout")):
        try:
            download_parallel("https://example.invalid/file", Path(folder)/"file.part", 10, 1)
        except TimeoutError:
            pass
        else:
            raise AssertionError("Expected the network failure to propagate")
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parent,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
