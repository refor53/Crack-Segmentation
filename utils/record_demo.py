"""Record the actual Streamlit viewer as demo/viewer.gif; see utils/README.md."""

import argparse
import csv
import io
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "demo/viewer.gif")
    args = parser.parse_args()
    if not (root / "dataset/multi-source_pavement_carc_k2026/extracted/01_ground_gopro").is_dir():
        raise SystemExit("Download and extract GoPro data before recording the demo.")
    split_file = next((root / "dataset/multi-source_pavement_carc_k2026/extracted/splits").rglob("final_split_all_groups.csv"))
    with split_file.open(encoding="utf-8-sig", newline="") as source:
        search_id = next(row["image_id"] for row in csv.DictReader(source)
                         if row["group"] == "gopro_5ft" and row["split"] == "train")
    with socket.socket() as address:
        address.bind(("127.0.0.1", 0))
        port = address.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    frames = []
    with tempfile.TemporaryDirectory(prefix="crack-viewer-demo-") as temporary:
        with (Path(temporary) / "server.log").open("w+") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "streamlit", "run", str(root / "utils/dataset_viewer.py"),
                 "--server.address", "127.0.0.1", "--server.port", str(port),
                 "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                cwd=root, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(120):
                    try:
                        with urllib.request.urlopen(url + "/_stcore/health", timeout=1):
                            break
                    except OSError:
                        if server.poll() is not None:
                            raise RuntimeError("Temporary viewer failed to start")
                        time.sleep(0.25)
                else:
                    raise RuntimeError("Temporary viewer startup timed out")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
                    page = browser.new_page(viewport={"width": 1440, "height": 1040}, device_scale_factor=1)
                    page.set_default_timeout(30000)
                    page.goto(url, wait_until="domcontentloaded")
                    page.get_by_role("heading", name="균열 데이터 뷰어", exact=True).wait_for()

                    def capture():
                        page.wait_for_timeout(1000)
                        page.wait_for_function("Array.from(document.images).filter(i => i.getBoundingClientRect().width > 0).every(i => i.complete && i.naturalWidth > 0)")
                        frame = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
                        frame.thumbnail((1100, 900), Image.Resampling.LANCZOS)
                        frames.append(frame)

                    page.get_by_role("heading", name="GoPro_3ft__000001", exact=True).wait_for()
                    capture()
                    page.get_by_role("button", name="다음 →", exact=True).click()
                    page.get_by_role("heading", name="GoPro_3ft__000002", exact=True).wait_for()
                    capture()
                    page.get_by_role("combobox").nth(2).click()
                    page.get_by_role("option", name="train", exact=True).click()
                    capture()
                    search = page.get_by_role("textbox", name="파일명 검색", exact=True)
                    search.fill(search_id)
                    search.press("Enter")
                    page.get_by_role("heading", name=search_id, exact=True).wait_for()
                    capture()
                    search.fill("")
                    search.press("Enter")
                    page.get_by_role("tab", name="데이터 요약", exact=True).click()
                    capture()
                    browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
    palette = frames[0].quantize(colors=128)
    frames = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(args.output, save_all=True, append_images=frames[1:],
                   duration=[2200, 1800, 2200, 2200, 1800], loop=0, optimize=True)
    print(f"Saved {args.output} ({args.output.stat().st_size:,} bytes, {len(frames)} frames)")


if __name__ == "__main__":
    main()
