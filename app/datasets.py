from __future__ import annotations

import json
import struct
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np
import scipy.io as sio
from PIL import Image

from .config import AppPaths, load_settings, resolve_dataset_root
from .db import CatalogueDB
from .registry import ReleaseRegistry, load_jsonl
from .util import pixel_sha256, safe_child, sha256_file


DATASET_INFO = {
    "oct5k": {"name": "OCT5K", "root_key": "oct5k_annotations"},
    "aroi": {"name": "AROI", "root_key": "aroi"},
    "duke_amd": {"name": "Duke AMD/control", "root_key": "duke_amd"},
    "jhu": {"name": "JHU HC/MS", "root_key": "jhu"},
    "duke_dme": {"name": "Duke DME 2015", "root_key": "duke_dme"},
    "custom": {"name": "Custom", "root_key": None},
}

JHU_HEADER = [
    ("version", "12s"), ("size_x", "i"), ("num_bscans", "i"), ("size_z", "i"),
    ("scale_x", "d"), ("distance", "d"), ("scale_z", "d"), ("size_x_slo", "i"),
    ("size_y_slo", "i"), ("scale_x_slo", "d"), ("scale_y_slo", "d"),
    ("field_size_slo", "i"), ("scan_focus", "d"), ("scan_position", "4s"),
    ("exam_time", "q"), ("scan_pattern", "i"), ("bscan_hdr_size", "i"),
]


def _safe_jhu_header(path: Path) -> dict:
    with path.open("rb") as handle:
        raw = handle.read(2048)
    values = struct.unpack_from("<" + "".join(kind for _, kind in JHU_HEADER), raw, 0)
    full = dict(zip((name for name, _ in JHU_HEADER), values))
    if not full["version"].startswith(b"HSF-OCT"):
        raise ValueError(f"{path.name} is not an HSF OCT volume")
    return {key: full[key] for key in (
        "size_x", "num_bscans", "size_z", "scale_x", "scale_z",
        "size_x_slo", "size_y_slo", "bscan_hdr_size",
    )}


def _read_jhu_scan(path: Path, bscan: int) -> np.ndarray:
    h = _safe_jhu_header(path)
    if not 0 <= bscan < h["num_bscans"]:
        raise IndexError(bscan)
    nx, nz = h["size_x"], h["size_z"]
    base = 2048 + h["size_x_slo"] * h["size_y_slo"]
    step = h["bscan_hdr_size"] + nx * nz * 4
    with path.open("rb") as handle:
        handle.seek(base + bscan * step + h["bscan_hdr_size"])
        values = np.frombuffer(handle.read(nx * nz * 4), "<f4").reshape(nz, nx).astype(np.float64)
    bad = ~np.isfinite(values) | (values > 1e30)
    values[bad] = 0.0
    return np.round(255.0 * np.clip(values, 0.0, 1.0) ** 0.25).astype(np.uint8)


@lru_cache(maxsize=4)
def _mat_images(path_text: str) -> np.ndarray:
    return sio.loadmat(path_text, variable_names=["images"])["images"]


class DatasetCatalogue:
    def __init__(self, paths: AppPaths, registry: ReleaseRegistry, db: CatalogueDB):
        self.paths = paths
        self.registry = registry
        self.db = db
        self.settings = load_settings(paths)
        self.roots = {
            key: resolve_dataset_root(paths, value)
            for key, value in self.settings["dataset_roots"].items()
        }
        self.rows: dict[str, list[dict]] = {}
        self.by_id: dict[str, dict] = {}
        for dataset, meta in registry.manifest["scan_indexes"].items():
            path = paths.registry / meta["path"]
            if not path.exists():
                raise RuntimeError(f"missing scan index: {path}")
            if sha256_file(path).lower() != meta["sha256"].lower():
                raise RuntimeError(f"scan-index hash mismatch: {dataset}")
            values = load_jsonl(path)
            if len(values) != meta["rows"]:
                raise RuntimeError(f"scan-index count mismatch: {dataset}")
            self.rows[dataset] = values
            self.by_id.update({row["scan_id"]: row for row in values})
        self._pixel_validation: dict[str, tuple[bool, str]] = {}

    def datasets(self) -> list[dict]:
        result = []
        for dataset, info in DATASET_INFO.items():
            if dataset == "custom":
                count = len(self.db.list_custom())
                installed = True
            else:
                count = len(self.rows.get(dataset, []))
                root = self.roots.get(info["root_key"])
                installed = bool(root and root.exists())
            result.append({
                "dataset": dataset,
                "name": info["name"],
                "scan_count": count,
                "installed": installed,
                "read_only": dataset != "custom",
            })
        return result

    def groups(self, dataset: str) -> list[dict]:
        if dataset == "custom":
            counts = Counter(json.loads(row["origin_json"]).get("group", "Custom") for row in self.db.list_custom())
        else:
            counts = Counter(row.get("group", "Other") for row in self.rows.get(dataset, []))
        return [{"group": key, "count": counts[key]} for key in sorted(counts, key=str)]

    def list_scans(
        self, dataset: str, group: str | None = None, search: str | None = None,
        offset: int = 0, limit: int = 100,
    ) -> dict:
        if dataset == "custom":
            values = [self._custom_public(row) for row in self.db.list_custom()]
        else:
            values = self.rows.get(dataset, [])
        if group:
            values = [row for row in values if str(row.get("group")) == group]
        if search:
            needle = search.casefold()
            values = [row for row in values if needle in " ".join(
                str(row.get(key, "")) for key in ("scan_id", "label", "parent", "group")
            ).casefold()]
        total = len(values)
        page = [self.public_scan(row) for row in values[offset:offset + limit]]
        return {"total": total, "offset": offset, "limit": limit, "scans": page}

    def get(self, scan_id: str) -> dict:
        if scan_id.startswith("custom-"):
            row = self.db.get_custom(scan_id)
            if not row:
                raise KeyError(scan_id)
            return self._custom_public(row)
        if scan_id not in self.by_id:
            raise KeyError(scan_id)
        return self.by_id[scan_id]

    def public_scan(self, row: dict) -> dict:
        positions = row.get("prediction_positions", {})
        return {
            "scan_id": row["scan_id"], "dataset": row["dataset"], "subset": row.get("subset"),
            "group": row.get("group"), "parent": row.get("parent"), "label": row.get("label"),
            "width": row["width"], "height": row["height"],
            "axial_um": row.get("axial_um"), "lateral_um": row.get("lateral_um"),
            "lateral_um_range": row.get("lateral_um_range"),
            "spacing_provenance": row.get("spacing_provenance"),
            "views": sorted(positions), "prediction_count_hint": len(positions),
            "development_warning": row.get("development_warning"),
            "read_only": row["dataset"] != "custom",
        }

    def _custom_public(self, row: dict) -> dict:
        origin = json.loads(row["origin_json"])
        return {
            "scan_id": row["scan_id"], "dataset": "custom", "subset": "custom",
            "group": origin.get("group", "Custom"), "parent": origin.get("source_dataset", "Imported"),
            "label": row["display_id"], "width": row["width"], "height": row["height"],
            "axial_um": row["axial_um"], "lateral_um": row["lateral_um"],
            "spacing_provenance": row["spacing_provenance"], "views": ["custom"],
            "prediction_count_hint": len(self.db.list_results(row["scan_id"])),
            "development_warning": origin.get("development_warning"), "read_only": False,
        }

    def load_image(self, scan_id: str) -> np.ndarray:
        row = self.get(scan_id)
        dataset = row["dataset"]
        if dataset == "custom":
            db_row = self.db.get_custom(scan_id)
            path = safe_child(self.paths.custom, Path(db_row["canonical_path"]))
            return np.asarray(Image.open(path), dtype=np.uint8)
        info = DATASET_INFO[dataset]
        root = self.roots[info["root_key"]]
        locator = row["locator"]
        if dataset in ("oct5k", "aroi"):
            path = safe_child(root, root / locator)
            image = np.asarray(Image.open(path))
            if image.ndim == 3:
                if not np.array_equal(image[..., 0], image[..., 1]) or not np.array_equal(image[..., 0], image[..., 2]):
                    raise ValueError("built-in image is not greyscale")
                image = image[..., 0]
            return image.astype(np.uint8, copy=False)
        if dataset == "jhu":
            path = safe_child(root, root / "vol" / f"{locator['eye']}.vol")
            return _read_jhu_scan(path, int(locator["bscan"]))
        if dataset == "duke_dme":
            path = safe_child(root, root / f"{locator['subject']}.mat")
            return np.asarray(_mat_images(str(path))[:, :, int(locator["bscan"])], dtype=np.uint8)
        if dataset == "duke_amd":
            path = safe_child(root, root / locator["diagnosis"] / f"{locator['subject']}.mat")
            return np.asarray(_mat_images(str(path))[:, :, int(locator["bscan"])], dtype=np.uint8)
        raise KeyError(dataset)

    def validate_pixels(self, scan_id: str) -> tuple[bool, str]:
        if scan_id in self._pixel_validation:
            return self._pixel_validation[scan_id]
        row = self.get(scan_id)
        expected = row.get("pixel_sha256")
        if not expected:
            value = (True, "no released pixel hash; display only")
        else:
            actual = pixel_sha256(self.load_image(scan_id))
            value = (actual == expected, "matched" if actual == expected else "pixel hash mismatch")
        self._pixel_validation[scan_id] = value
        return value

