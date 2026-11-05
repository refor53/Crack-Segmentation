"""Fetch Zenodo JSON, download its files into raw/, and extract each ZIP."""

import argparse
import hashlib
import json
import subprocess
import fcntl
from pathlib import Path

from extract_data import extract_preserving


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("json_url", nargs="?", default="https://zenodo.org/records/22697998/export/json",
                    help="Zenodo /records/<id>/export/json URL")
parser.add_argument("--output-dir", type=Path,
                    default=Path(__file__).resolve().parents[1] / "dataset/multi-source_pavement_carc_k2026",
                    help="Dataset directory")
parser.add_argument("--files", nargs="+", help="Download and extract only these exact filenames")
parser.add_argument("--connections", type=int, choices=range(1, 9), default=1,
                    help="Connections per file (default: 1, using wget)")
args = parser.parse_args()

dataset_dir = args.output_dir.resolve()
raw_dir = dataset_dir / "raw"
raw_dir.mkdir(parents=True, exist_ok=True)
download_lock = (dataset_dir / ".download.lock").open("a")
try:
    fcntl.flock(download_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit(f"Another download is using {dataset_dir}")

# 1. wget으로 JSON 받기
print("[1/4] Downloading JSON", flush=True)
json_path = dataset_dir / "zenodo-record.json"
json_partial = dataset_dir / "zenodo-record.json.part"
subprocess.run(
    ["wget", "--timeout=60", "--tries=3", "-O", str(json_partial), "--", args.json_url],
    check=True,
)

# 2. JSON이 정상인지, 필요한 파일 정보가 있는지 확인하기
print("[2/4] Validating JSON", flush=True)
record = json.loads(json_partial.read_text(encoding="utf-8"))
if not isinstance(record, dict) or not record.get("id"):
    raise SystemExit("Invalid Zenodo JSON: missing record ID.")
files = record.get("files", {}).get("entries", {})
if not isinstance(files, dict) or not files:
    raise SystemExit("Invalid Zenodo JSON: missing files.entries.")
for name, info in files.items():
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise SystemExit(f"Invalid filename: {name!r}")
    if not isinstance(info.get("size"), int) or info["size"] < 0:
        raise SystemExit(f"Missing or invalid file size: {name}")
    if not info.get("checksum", "").startswith("md5:"):
        raise SystemExit(f"Missing MD5 checksum: {name}")
    if not info.get("links", {}).get("content", "").startswith("https://"):
        raise SystemExit(f"Missing HTTPS download URL: {name}")
json_partial.replace(json_path)
print(f"Record {record['id']}: {len(files)} files", flush=True)
if args.files:
    missing = set(args.files) - files.keys()
    if missing:
        raise SystemExit(f"Unknown files: {sorted(missing)}")
    files = {name: files[name] for name in dict.fromkeys(args.files)}
    print(f"Selected {len(files)} files: {', '.join(files)}", flush=True)

# 3. JSON의 링크를 읽어 raw/에 다운로드하고 크기·체크섬 확인하기
print("[3/4] Downloading and verifying files", flush=True)
for name, info in files.items():
    target = raw_dir / name
    partial = raw_dir / (name + ".part")
    source = target if target.exists() else partial
    if not target.exists():
        if args.connections > 1:
            from parallel_download import download_parallel
            download_parallel(info["links"]["content"], partial, info["size"], args.connections)
        else:
            subprocess.run(
                ["wget", "-c", "--timeout=60", "--tries=3", "--progress=dot:giga",
                 "-O", str(partial), "--", info["links"]["content"]],
                check=True,
            )
    with source.open("rb") as downloaded:
        checksum = "md5:" + hashlib.file_digest(downloaded, "md5").hexdigest()
    if source.stat().st_size != info["size"] or checksum != info["checksum"]:
        raise SystemExit(f"Verification failed: {source}. Remove this file and rerun.")
    if source == partial:
        partial.replace(target)
    print(f"Verified: {name}", flush=True)

# 4. 각 ZIP을 extracted/<ZIP 이름>/ 폴더에 풀기
print("[4/4] Extracting ZIP files", flush=True)
for name in files:
    if not name.lower().endswith(".zip"):
        continue
    folder = dataset_dir / "extracted" / Path(name).stem
    added, skipped = extract_preserving(raw_dir / name, folder)
    print(f"Extracted: {folder} (new {added}, kept {skipped}; ZIP retained)", flush=True)

print(f"Done: {dataset_dir}", flush=True)
