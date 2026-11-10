"""Portable OCT5K staging tool used by the viewer setup guide.

It applies the project's verified Pillow bilinear 512x512 route. Users supply
the raw Rasti root, annotation root, and paths CSV. It never prints or stores an
archive password.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from PIL import Image


TAG = "Macular-Dataset-R.Rasti_old"


def stage_images(raw_root: Path, annotation_root: Path, paths_csv: Path) -> dict[str, int]:
    """Stage one OCT5K path manifest and return auditable outcome counts."""
    written = skipped = missing = 0
    with paths_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if len(row) < 2 or TAG not in row[1]:
                skipped += 1
                continue
            relative = row[1][row[1].find(TAG) + len(TAG):].lstrip("/\\")
            source = raw_root / relative
            target_text = row[0].strip()
            while target_text.startswith("../"):
                target_text = target_text[3:]
            target = annotation_root / target_text
            if target.suffix.lower() == ".jpeg":
                target = target.with_suffix(".png")
            if not source.exists():
                missing += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(source) as opened:
                image = opened if opened.mode in ("L", "RGB") else opened.convert("L")
                image.resize((512, 512), Image.Resampling.BILINEAR).save(target)
            written += 1
    return {"written": written, "skipped_other_source": skipped, "missing": missing}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--annotation-root", type=Path, required=True)
    parser.add_argument("--paths-csv", type=Path, required=True)
    args = parser.parse_args()
    print(stage_images(args.raw_root, args.annotation_root, args.paths_csv))


if __name__ == "__main__":
    main()

