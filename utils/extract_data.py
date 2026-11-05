"""Extract downloaded ZIP archives without deleting ZIPs or replacing existing files."""

import argparse
import shutil
import zipfile
from pathlib import Path


def extract_preserving(archive_path: Path, destination: Path) -> tuple[int, int]:
    destination = destination.resolve()
    extracted = skipped = 0
    with zipfile.ZipFile(archive_path) as archive:
        # Validate every member before writing any files.
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination):
                raise ValueError(f"Unsafe ZIP path: {member.filename}")
        destination.mkdir(parents=True, exist_ok=True)
        for member in archive.infolist():
            target = destination / member.filename
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists():
                skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # Write a temporary sibling, so interruption never leaves a partial image.
            temporary = target.with_name(target.name + ".extracting")
            try:
                with archive.open(member) as source, temporary.open("wb") as output:
                    shutil.copyfileobj(source, output)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            extracted += 1
    return extracted, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    args = parser.parse_args()
    archives = sorted((args.dataset_dir / "raw").glob("*.zip"))
    if not archives:
        raise SystemExit("No completed ZIP files found in raw/.")
    for archive in archives:
        destination = args.dataset_dir / "extracted" / archive.stem
        added, skipped = extract_preserving(archive, destination)
        print(f"{archive.name}: extracted {added}, kept {skipped}; ZIP retained", flush=True)


if __name__ == "__main__":
    main()
