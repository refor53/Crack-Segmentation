# Utilities / 유틸리티

See the [root README](../README.md) for setup, resume and viewer commands.

설치·이어받기·뷰어 실행은 루트 README를 참고하세요.

Download only selected files / 선택한 파일만 다운로드:

```bash
uv run --locked --extra viewer python utils/download_data.py --connections 4 \
  --files README.md LICENSE.txt SHA256SUMS.txt splits.zip 01_ground_gopro.zip
```

Extract completed ZIPs, preserving ZIPs and existing files / 받은 ZIP 압축 해제, 기존 파일 유지:

```bash
uv run --locked --extra viewer python utils/extract_data.py \
  --dataset-dir dataset/multi-source_pavement_carc_k2026
```

Verify / 검증:

```bash
uv run --locked --extra viewer python -m unittest discover -s utils -p 'test_*.py'
```

Regenerate the demo after extracting GoPro data / GoPro 압축 해제 후 데모 다시 만들기:

```bash
uv run --locked --extra viewer --with playwright==1.56.0 python -m playwright install --with-deps chromium
uv run --locked --extra viewer --with playwright==1.56.0 python utils/record_demo.py
```

The recorder uses a temporary local viewer. Only `demo/viewer.gif` is kept.

임시 로컬 뷰어에서 녹화하며 `demo/viewer.gif`만 남깁니다.
