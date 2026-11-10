from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(ROOT))

from app.config import AppPaths
from app.custom import CustomService, canonicalize_upload
from app.datasets import DatasetCatalogue
from app.db import CatalogueDB
from app.inference import infer_one
from app.registry import ReleaseRegistry
from app.surface_model import SurfaceUNet


def test_surface_model_parameter_count():
    assert sum(parameter.numel() for parameter in SurfaceUNet().parameters()) == 7_762_531


def test_custom_input_rules():
    array = np.arange(64, dtype=np.uint8).reshape(8, 8)
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    decoded, meta = canonicalize_upload(buffer.getvalue(), "scan.png", False)
    assert np.array_equal(decoded, array)
    assert not meta["lossy_warning"]

    rgb = np.stack([array, array, (array + 1).astype(np.uint8)], axis=-1)
    buffer = io.BytesIO(); Image.fromarray(rgb).save(buffer, format="PNG")
    try:
        canonicalize_upload(buffer.getvalue(), "colour.png", False)
    except ValueError as exc:
        assert "not greyscale" in str(exc)
    else:
        raise AssertionError("non-grey RGB input was accepted")


def test_add_builtin_to_custom_is_isolated_and_deduplicated(tmp_path):
    paths = AppPaths(
        app_root=ROOT, workspace_root=WORKSPACE, registry=ROOT / "registry",
        state=tmp_path / "state", custom=tmp_path / "custom", trash=tmp_path / "trash",
        static=ROOT / "static",
    )
    paths.ensure_owned_dirs()
    registry = ReleaseRegistry(paths)
    db = CatalogueDB(paths.state / "catalogue.sqlite")
    catalogue = DatasetCatalogue(paths, registry, db)
    service = CustomService(paths, db, catalogue)
    first, created_first = service.add_builtin("oct5k-man-0000", True)
    second, created_second = service.add_builtin("oct5k-man-0000", True)
    assert created_first is True
    assert created_second is False
    assert first["scan_id"] == second["scan_id"]
    assert first["dataset"] == "custom"
    assert catalogue.by_id["oct5k-man-0000"]["prediction_positions"]
    assert db.list_results(first["scan_id"]) == []


def test_single_scan_cpu_reproduces_stored_oct5k_within_provisional_limits():
    registry = ReleaseRegistry(AppPaths(
        app_root=ROOT, workspace_root=WORKSPACE, registry=ROOT / "registry",
        state=ROOT / "state", custom=ROOT / "custom_dataset", trash=ROOT / "trash", static=ROOT / "static",
    ))
    first_scan = json.loads((ROOT / "registry/scan_indexes/oct5k.jsonl").read_text(encoding="utf-8").splitlines()[0])
    image = ROOT / "datasets/oct5k_annotations" / first_scan["locator"]
    model = registry.model_by_id["V111__seed_000"]
    mean, _, provenance = infer_one(
        image, registry.checkpoint_path("V111__seed_000"), model["checkpoint_sha256"], None, None, "cpu"
    )
    with np.load(ROOT / "results/exploratory/predictions/V111__all41__seed_000.npz", allow_pickle=False) as archive:
        stored = archive["mean_px"][0]
    difference = np.abs(mean - stored)
    assert difference.mean() <= 0.01
    assert np.percentile(difference, 99) <= 0.15
    assert difference.max() <= 1.0
    assert provenance["calibration"] == "uncalibrated_exploratory"

