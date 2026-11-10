from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from .config import AppPaths
from .datasets import DatasetCatalogue
from .db import CatalogueDB
from .util import atomic_json, pixel_sha256


MAX_ROWS = 2048
MAX_COLS = 2048
MAX_PIXELS = 4_194_304


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonicalize_upload(data: bytes, filename: str, confirm_16bit: bool) -> tuple[np.ndarray, dict]:
    try:
        image = Image.open(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"cannot decode image: {exc}") from exc
    if getattr(image, "n_frames", 1) != 1:
        raise ValueError("multi-page images are not supported")
    width, height = image.size
    if height > MAX_ROWS or width > MAX_COLS or height * width > MAX_PIXELS:
        raise ValueError(f"image exceeds the version-1 limit of {MAX_ROWS}x{MAX_COLS} and {MAX_PIXELS} pixels")
    mode = image.mode
    array = np.asarray(image)
    if np.issubdtype(array.dtype, np.floating):
        raise ValueError("floating-point images are not supported")
    if array.ndim == 3:
        rgb = np.asarray(image.convert("RGB"))
        if not (np.array_equal(rgb[..., 0], rgb[..., 1]) and np.array_equal(rgb[..., 0], rgb[..., 2])):
            raise ValueError("RGB image is not greyscale")
        array = rgb[..., 0]
    if array.ndim != 2:
        raise ValueError("image must decode to one greyscale plane")
    if array.dtype == np.uint16 or mode.startswith("I;16"):
        if not confirm_16bit:
            raise ValueError("16-bit display-scaled confirmation is required")
        array = np.rint(array.astype(np.float64) / 257.0).clip(0, 255).astype(np.uint8)
    elif array.dtype == np.uint8:
        array = array.astype(np.uint8, copy=False)
    elif np.issubdtype(array.dtype, np.integer):
        maximum = np.iinfo(array.dtype).max
        array = np.rint(array.astype(np.float64) * 255.0 / maximum).clip(0, 255).astype(np.uint8)
    else:
        raise ValueError(f"unsupported image dtype: {array.dtype}")
    return np.ascontiguousarray(array), {
        "original_filename": Path(filename).name,
        "original_mode": mode,
        "original_dtype": str(np.asarray(image).dtype),
        "lossy_warning": Path(filename).suffix.lower() in (".jpg", ".jpeg"),
    }


class CustomService:
    def __init__(self, paths: AppPaths, db: CatalogueDB, catalogue: DatasetCatalogue):
        self.paths = paths
        self.db = db
        self.catalogue = catalogue

    def register_upload(
        self, data: bytes, filename: str, orientation_confirmed: bool,
        confirm_16bit: bool, axial_um: float | None, lateral_um: float | None,
        spacing_provenance: str | None,
    ) -> tuple[dict, bool]:
        if not orientation_confirmed:
            raise ValueError("orientation confirmation is required")
        image, source = canonicalize_upload(data, filename, confirm_16bit)
        origin = {
            "kind": "external_upload", "group": "Imported", "private_original_filename": source["original_filename"],
            "lossy_warning": source["lossy_warning"], "burned_in_text_warning_acknowledged": True,
        }
        return self._register(image, origin, axial_um, lateral_um, spacing_provenance, data, Path(filename).suffix)

    def add_builtin(self, scan_id: str, orientation_confirmed: bool) -> tuple[dict, bool]:
        if not orientation_confirmed:
            raise ValueError("orientation confirmation is required")
        source = self.catalogue.get(scan_id)
        if source["dataset"] == "custom":
            raise ValueError("scan is already Custom")
        image = self.catalogue.load_image(scan_id)
        origin = {
            "kind": "built_in_copy", "group": "Copied from built-in",
            "source_dataset": source["dataset"], "source_scan_id": scan_id,
            "development_warning": source.get("development_warning"),
            "aroi_path_note": "AX1-style calibrated path; not AX2, AX3, or AX4" if source["dataset"] == "aroi" else None,
        }
        return self._register(
            image, origin, source.get("axial_um"), source.get("lateral_um"),
            "built-in metadata" if source.get("axial_um") is not None else None,
            None, ".png",
        )

    def _register(
        self, image: np.ndarray, origin: dict, axial_um: float | None,
        lateral_um: float | None, spacing_provenance: str | None,
        original_bytes: bytes | None, original_suffix: str,
    ) -> tuple[dict, bool]:
        digest = pixel_sha256(image)
        existing = self.db.find_custom_by_hash(digest)
        if existing:
            return self.catalogue._custom_public(existing), False
        raw_uuid = uuid.uuid4().hex
        scan_id = f"custom-{raw_uuid}"
        display_id = f"CUS-{raw_uuid[:12].upper()}"
        folder = self.paths.custom / "scans" / scan_id
        temp = Path(tempfile.mkdtemp(prefix=f".{scan_id}-", dir=self.paths.custom / "scans"))
        try:
            canonical = temp / "image.png"
            Image.fromarray(image, mode="L").save(canonical, format="PNG")
            original_path = None
            if original_bytes is not None:
                suffix = original_suffix.lower() if original_suffix else ".bin"
                original = temp / f"original{suffix}"
                original.write_bytes(original_bytes)
                original_path = str(folder / original.name)
            manifest = {
                "schema": 1, "scan_id": scan_id, "display_id": display_id,
                "pixel_sha256": digest, "width": int(image.shape[1]), "height": int(image.shape[0]),
                "axial_um": axial_um, "lateral_um": lateral_um,
                "spacing_provenance": spacing_provenance, "canonicalisation": "custom_canonical_u8_v1",
                "orientation_confirmed": True, "origin": origin, "created_utc": utc_now(),
                "research_use_only": True,
            }
            atomic_json(temp / "manifest.json", manifest)
            os.replace(temp, folder)
            record = {
                "scan_id": scan_id, "display_id": display_id, "pixel_sha256": digest,
                "canonical_path": str(folder / "image.png"), "manifest_path": str(folder / "manifest.json"),
                "original_path": original_path, "width": int(image.shape[1]), "height": int(image.shape[0]),
                "axial_um": axial_um, "lateral_um": lateral_um, "spacing_provenance": spacing_provenance,
                "origin_json": json.dumps(origin, sort_keys=True), "status": "active", "created_utc": manifest["created_utc"],
            }
            self.db.insert_custom(record)
            return self.catalogue._custom_public(record), True
        finally:
            if temp.exists():
                shutil.rmtree(temp, ignore_errors=True)

    def trash(self, scan_id: str) -> None:
        row = self.db.get_custom(scan_id)
        if not row:
            raise KeyError(scan_id)
        folder = Path(row["canonical_path"]).parent
        target = self.paths.trash / scan_id
        if target.exists():
            raise FileExistsError(target)
        os.replace(folder, target)
        self.db.set_custom_status(scan_id, "trashed")

