"""Run with: uv run --extra viewer streamlit run utils/dataset_viewer.py"""

import csv
import json
import random
from collections import Counter
from pathlib import Path

import streamlit as st
from PIL import Image


DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "dataset/multi-source_pavement_carc_k2026"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


@st.cache_data(ttl=20, show_spinner=False)
def scan_dataset(dataset: str) -> tuple[list[dict], int]:
    """Match local image/mask stems; CSV paths refer to the author's Windows PC."""
    extracted = Path(dataset) / "extracted"
    metadata = {}
    for split_file in sorted(extracted.rglob("final_split_all_groups.csv")):
        with split_file.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                key = (row.get("group", "").casefold(), row.get("image_id", "").casefold())
                metadata[key] = row
    images, masks = [], {}
    for path in sorted(extracted.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in IMAGE_EXTENSIONS:
            continue
        folder = path.parent.name.casefold()
        key = (str(path.parent.parent), path.stem.casefold())
        if folder == "masks":
            masks[key] = str(path)
        elif folder in {"images", "images and jsons"}:
            images.append(path)
    records = []
    for image in images:
        group = image.parent.parent.name
        row = metadata.get((group.casefold(), image.stem.casefold()), {})
        try:
            ratio = float(row["crack_ratio"])
        except (KeyError, ValueError, TypeError):
            ratio = None
        records.append({
            "image_id": image.stem,
            "group": group,
            "archive": image.relative_to(extracted).parts[0],
            "split": row.get("split") or "미지정",
            "source": row.get("source_family") or "미지정",
            "image": str(image),
            "mask": masks.get((str(image.parent.parent), image.stem.casefold())),
            "crack_ratio": ratio,
            "metadata": row,
        })
    return records, len(metadata)


@st.cache_data(max_entries=8, show_spinner=False)
def load_preview(image_path: str, mask_path: str | None, max_size: int):
    with Image.open(image_path) as source:
        original_size = source.size
        image = source.convert("RGB")
    image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    mask = None
    mask_size = None
    if mask_path:
        with Image.open(mask_path) as source:
            mask_size = source.size
            mask = source.convert("L")
        # Never interpolate labels or silently stretch a mismatched annotation.
        if mask_size == original_size:
            mask = mask.resize(image.size, Image.Resampling.NEAREST)
        else:
            mask.thumbnail((max_size, max_size), Image.Resampling.NEAREST)
    return image, mask, original_size, mask_size


def make_overlay(image: Image.Image, mask: Image.Image, opacity: float) -> Image.Image:
    foreground = mask.point(lambda pixel: 255 if pixel > 0 else 0)
    colored = Image.blend(image, Image.new("RGB", image.size, "#ff4b4b"), opacity)
    return Image.composite(colored, image, foreground)


def download_status(dataset: Path) -> tuple[list[dict], int, int]:
    metadata_file = dataset / "zenodo-record.json"
    if not metadata_file.exists():
        return [], 0, 0
    record = json.loads(metadata_file.read_text(encoding="utf-8"))
    rows, received, total = [], 0, 0
    for name, info in record.get("files", {}).get("entries", {}).items():
        expected = info["size"]
        target = dataset / "raw" / name
        partial = target.with_name(name + ".part")
        actual = target.stat().st_size if target.exists() else partial.stat().st_size if partial.exists() else 0
        complete = target.exists() and actual == expected
        rows.append({
            "파일": name,
            "상태": "다운로드 완료" if complete else "부분 다운로드" if actual else "대기",
            "받은 용량 (MB)": round(actual / 1e6, 2),
            "전체 용량 (MB)": round(expected / 1e6, 2),
            "압축 해제 폴더": ("있음" if (dataset / "extracted" / Path(name).stem).is_dir() else "—") if name.endswith(".zip") else "—",
        })
        received += min(actual, expected)
        total += expected
    return rows, received, total


def show_download_status(dataset: Path) -> None:
    try:
        rows, received, total = download_status(dataset)
    except (OSError, ValueError, KeyError, TypeError) as error:
        st.warning(f"다운로드 상태를 읽을 수 없습니다: {error}")
        return
    if not rows:
        st.info("이 폴더에 다운로드 메타데이터가 없습니다.")
        return
    st.progress(received / total if total else 0, text=f"{received / 1e9:.2f} / {total / 1e9:.2f} GB")
    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption("새로고침하면 최신 상태를 불러옵니다. 원본 ZIP은 raw/에 유지됩니다.")


def move_sample(delta: int, count: int) -> None:
    st.session_state.sample_number = max(1, min(count, st.session_state.sample_number + delta))


def random_sample(count: int) -> None:
    st.session_state.sample_number = random.randint(1, count)


def main() -> None:
    st.set_page_config(page_title="균열 데이터 뷰어", page_icon="🔎", layout="wide")
    st.title("균열 데이터 뷰어")
    st.caption("포장 이미지와 정답 마스크를 비교하고 촬영 조건별로 탐색하세요.")
    with st.sidebar:
        st.header("데이터 선택")
        dataset_text = st.text_input("데이터셋 폴더", str(DEFAULT_DATASET), key="dataset_root")
        if st.button("데이터 새로고침", width="stretch"):
            st.cache_data.clear()
            st.rerun()
    dataset = Path(dataset_text).expanduser().resolve()
    if not dataset.is_dir():
        st.warning(f"데이터셋 폴더를 찾을 수 없습니다: {dataset}")
        return
    try:
        records, metadata_count = scan_dataset(str(dataset))
    except (OSError, csv.Error, UnicodeError) as error:
        st.error(f"데이터 목록을 읽을 수 없습니다: {error}")
        return
    if not records:
        st.info("아직 압축 해제된 이미지가 없습니다. 다운로드와 압축 해제가 끝난 뒤 새로고침하세요.")
        show_download_status(dataset)
        return
    with st.sidebar:
        archive = st.selectbox("데이터 묶음", ["전체"] + sorted({r["archive"] for r in records}))
        archive_records = [r for r in records if archive == "전체" or r["archive"] == archive]
        group = st.selectbox("촬영 그룹", ["전체"] + sorted({r["group"] for r in archive_records}))
        split = st.selectbox("데이터 분할", ["전체"] + sorted({r["split"] for r in records}))
        keyword = st.text_input("파일명 검색", placeholder="예: GoPro_3ft__000001")
        paired_only = st.checkbox("마스크가 있는 이미지만", value=True)
        st.divider()
        opacity = st.slider("마스크 불투명도", 0.0, 1.0, 0.5, 0.05)
        max_size = st.select_slider("미리보기 최대 크기", [800, 1200, 1600, 2400], value=1200)
        st.caption("화면 표시 크기만 조절합니다. 원본 파일은 수정하지 않습니다.")
    filtered = [r for r in archive_records
                if (group == "전체" or r["group"] == group)
                and (split == "전체" or r["split"] == split)
                and keyword.casefold() in r["image_id"].casefold()
                and (not paired_only or r["mask"])]
    for column, label, value in zip(st.columns(4),
                                    ("사용 가능한 이미지", "마스크 연결", "전체 분할 목록", "필터 결과"),
                                    (len(records), sum(bool(r["mask"]) for r in records), metadata_count, len(filtered))):
        column.metric(label, f"{value:,}")
    if metadata_count > len(records):
        st.info(f"현재 {len(records):,}개 이미지가 준비되었습니다. 나머지 데이터가 압축 해제되면 새로고침으로 추가할 수 있습니다.")
    browse, summary, downloads = st.tabs(["이미지 탐색", "데이터 요약", "다운로드 상태"])
    with browse:
        if not filtered:
            st.info("조건에 맞는 이미지가 없습니다. 필터나 검색어를 바꿔 주세요.")
        else:
            signature = (str(dataset), archive, group, split, keyword, paired_only)
            if st.session_state.get("filter_signature") != signature:
                st.session_state.filter_signature = signature
                st.session_state.sample_number = 1
            st.session_state.sample_number = min(st.session_state.get("sample_number", 1), len(filtered))
            previous, following, shuffle, position = st.columns([1, 1, 1, 2])
            previous.button("← 이전", on_click=move_sample, args=(-1, len(filtered)),
                            disabled=st.session_state.sample_number == 1, width="stretch")
            following.button("다음 →", on_click=move_sample, args=(1, len(filtered)),
                             disabled=st.session_state.sample_number == len(filtered), width="stretch")
            shuffle.button("무작위", on_click=random_sample, args=(len(filtered),), width="stretch")
            position.number_input("이미지 번호", min_value=1, max_value=len(filtered), step=1, key="sample_number")
            record = filtered[st.session_state.sample_number - 1]
            st.subheader(record["image_id"])
            ratio = f" · 균열 비율 {record['crack_ratio']:.2%}" if record["crack_ratio"] is not None else ""
            st.caption(f"{record['group']} · {record['split']} · {st.session_state.sample_number} / {len(filtered)}{ratio}")
            try:
                image, mask, image_size, mask_size = load_preview(record["image"], record["mask"], max_size)
                original_column, mask_column, overlay_column = st.columns(3)
                original_column.image(image, caption=f"원본 · {image_size[0]} × {image_size[1]}", width="stretch")
                if mask is None:
                    mask_column.info("연결된 마스크가 없습니다.")
                else:
                    mask_column.image(mask, caption="정답 마스크", width="stretch")
                    if image_size != mask_size:
                        overlay_column.warning(f"이미지와 마스크 크기가 다릅니다: {image_size} / {mask_size}")
                    else:
                        overlay_column.image(make_overlay(image, mask, opacity), caption="겹쳐 보기 · 빨강 = 균열", width="stretch")
                with st.expander("파일 및 촬영 정보"):
                    st.write({k: record["metadata"][k] for k in ("platform", "device", "height", "unit", "image_width", "image_height", "crack_pixels", "total_pixels") if record["metadata"].get(k)})
                    st.code(record["image"])
                    if record["mask"]:
                        st.code(record["mask"])
            except (OSError, ValueError) as error:
                st.error(f"이미지를 읽을 수 없습니다. 새로고침 후 다시 확인하세요: {error}")
    with summary:
        st.caption("현재 필터에 해당하는 로컬 이미지 기준입니다.")
        counts = Counter((r["group"], r["split"]) for r in filtered)
        if counts:
            st.dataframe([{"촬영 그룹": key[0], "분할": key[1], "이미지 수": value}
                          for key, value in sorted(counts.items())], hide_index=True, width="stretch")
        missing_masks = [r["image_id"] for r in records if not r["mask"]]
        if missing_masks:
            st.warning(f"마스크가 연결되지 않은 이미지: {len(missing_masks)}개")
            st.write(missing_masks[:30])
    with downloads:
        show_download_status(dataset)


if __name__ == "__main__":
    main()
