"""Run: uv run --extra viewer python -m unittest discover -s utils -p 'test_*.py'"""

import csv
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image
from streamlit.testing.v1 import AppTest

from dataset_viewer import make_overlay, scan_dataset
from extract_data import extract_preserving


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        scan_dataset.clear()

    def make_dataset(self):
        for group in ("gopro_3ft", "gopro_5ft"):
            base = self.root / "extracted" / "01_ground_gopro" / group
            (base / "Images").mkdir(parents=True)
            (base / "Masks").mkdir()
            Image.new("RGB", (4, 4), (30, 60, 90)).save(base / "Images/frame.JPG")
            Image.new("L", (4, 4), 255).save(base / "Masks/frame.PNG")
        split = self.root / "extracted/splits/final_split_all_groups.csv"
        split.parent.mkdir(parents=True)
        with split.open("w", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=["image_id", "group", "split", "image_path", "crack_ratio"])
            writer.writeheader()
            for group, part in (("gopro_3ft", "train"), ("gopro_5ft", "test")):
                writer.writerow({"image_id": "frame", "group": group, "split": part,
                                 "image_path": "D:\\author\\unavailable\\frame.jpg", "crack_ratio": "0.25"})

    def test_pairs_use_local_group_and_stem_instead_of_windows_paths(self):
        self.make_dataset()
        records, total = scan_dataset(str(self.root))
        self.assertEqual(total, 2)
        self.assertEqual(len(records), 2)
        self.assertEqual({r["split"] for r in records}, {"train", "test"})
        for record in records:
            self.assertTrue(Path(record["image"]).is_file())
            self.assertEqual(Path(record["image"]).parent.parent, Path(record["mask"]).parent.parent)

    def test_overlay_changes_only_foreground(self):
        image = Image.new("RGB", (2, 1), (10, 20, 30))
        mask = Image.new("L", (2, 1), 0)
        mask.putpixel((1, 0), 1)
        result = make_overlay(image, mask, 1.0)
        self.assertEqual(result.getpixel((0, 0)), (10, 20, 30))
        self.assertEqual(result.getpixel((1, 0)), (255, 75, 75))
        self.assertEqual(image.getpixel((1, 0)), (10, 20, 30))

    def test_extract_keeps_zip_and_existing_files(self):
        archive = self.root / "data.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("Images/one.txt", "original")
            output.writestr("Images/two.txt", "second")
        folder = self.root / "extracted"
        (folder / "Images").mkdir(parents=True)
        existing = folder / "Images/one.txt"
        existing.write_text("keep my existing file")
        self.assertEqual(extract_preserving(archive, folder), (1, 1))
        self.assertEqual(existing.read_text(), "keep my existing file")
        self.assertEqual((folder / "Images/two.txt").read_text(), "second")
        self.assertTrue(archive.exists())
        self.assertEqual(extract_preserving(archive, folder), (0, 2))

    def test_unsafe_archive_writes_nothing(self):
        archive = self.root / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("safe.txt", "safe")
            output.writestr("../escape.txt", "unsafe")
        folder = self.root / "output"
        with self.assertRaises(ValueError):
            extract_preserving(archive, folder)
        self.assertFalse(folder.exists())
        self.assertFalse((self.root / "escape.txt").exists())

    def test_viewer_filters_navigation_and_empty_directory(self):
        self.make_dataset()
        app = AppTest.from_file(str(Path(__file__).with_name("dataset_viewer.py")), default_timeout=30)
        app.session_state["dataset_root"] = str(self.root)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "2")
        self.assertEqual(app.session_state["sample_number"], 1)
        next(button for button in app.button if button.label == "다음 →").click().run()
        self.assertEqual(app.session_state["sample_number"], 2)
        next(widget for widget in app.selectbox if widget.label == "데이터 분할").select("test").run()
        self.assertEqual(app.metric[3].value, "1")
        self.assertEqual(app.session_state["sample_number"], 1)
        next(widget for widget in app.text_input if widget.label == "파일명 검색").set_value("missing-image").run()
        self.assertEqual(app.metric[3].value, "0")
        self.assertFalse(app.exception)
        empty = self.root / "empty"
        empty.mkdir()
        app.text_input(key="dataset_root").set_value(str(empty)).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("압축 해제된 이미지" in item.value for item in app.info))


if __name__ == "__main__":
    unittest.main()
