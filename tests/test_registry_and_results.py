from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(ROOT))

from app.config import AppPaths
from app.datasets import DatasetCatalogue
from app.db import CatalogueDB
from app.registry import ReleaseRegistry
from app.results import ResultService


def services(tmp_path):
    paths = AppPaths(
        app_root=ROOT, workspace_root=WORKSPACE, registry=ROOT / "registry",
        state=tmp_path / "state", custom=tmp_path / "custom", trash=tmp_path / "trash",
        static=ROOT / "static",
    )
    paths.ensure_owned_dirs()
    registry = ReleaseRegistry(paths)
    db = CatalogueDB(paths.state / "catalogue.sqlite")
    catalogue = DatasetCatalogue(paths, registry, db)
    return paths, registry, db, catalogue, ResultService(registry, catalogue, db)


def test_registry_is_explicit_and_excludes_controls(tmp_path):
    _, registry, _, _, _ = services(tmp_path)
    assert len(registry.models) == 55
    assert len(registry.predictions) == 365
    assert len({item["checkpoint_sha256"] for item in registry.models}) == 55
    assert not any("CW" in item["model_id"] for item in registry.models)
    assert not any(Path(item["checkpoint"]).name != "source_best.pt" for item in registry.models)
    assert all(not Path(item["checkpoint"]).is_absolute() for item in registry.models)
    assert all(not Path(item["path"]).is_absolute() for item in registry.predictions)
    assert all((ROOT / item["checkpoint"]).is_file() for item in registry.models)
    assert all((ROOT / item["path"]).is_file() for item in registry.predictions)
    assert registry.model_by_id["V111__seed_000"]["role"] == "R*"
    assert registry.model_by_id["V100__seed_000"]["role"] == "C*"
    assert registry.model_by_id["B3_MT__seed_000"]["selected_weights"] == "teacher"


def test_scan_counts_and_result_coverage(tmp_path):
    _, _, _, catalogue, result_service = services(tmp_path)
    assert {item["dataset"]: item["scan_count"] for item in catalogue.datasets()} == {
        "oct5k": 4234, "aroi": 3072, "duke_amd": 38382,
        "jhu": 1715, "duke_dme": 610, "custom": 0,
    }
    assert result_service.list_for_scan("oct5k-man-0000")["available"] == 55
    aroi = next(row for row in catalogue.rows["aroi"] if row["prediction_positions"])
    assert result_service.list_for_scan(aroi["scan_id"], "aroi__ax1")["available"] == 55
    assert result_service.list_for_scan(aroi["scan_id"], "aroi__ax2")["available"] == 40
    assert result_service.list_for_scan("jhu-0000")["available"] == 40
    dme = next(row for row in catalogue.rows["duke_dme"] if row["prediction_positions"])
    assert result_service.list_for_scan(dme["scan_id"])["available"] == 40
    assert result_service.list_for_scan("duke-amd-00000")["available"] == 0


def test_dme_name_collision_is_resolved(tmp_path):
    _, registry, _, _, _ = services(tmp_path)
    oct_entry = registry.prediction_by_id["oct5k__dme__V111__seed_000"]
    duke_entry = registry.prediction_by_id["duke_dme__dme__V111__seed_000"]
    assert oct_entry["path"] != duke_entry["path"]
    with np.load(ROOT / oct_entry["path"], allow_pickle=False) as archive:
        assert archive["mean_px"].shape == (403, 3, 512)
    with np.load(ROOT / duke_entry["path"], allow_pickle=False) as archive:
        assert archive["mean_px"].shape == (110, 3, 768)


def test_seed_average_is_derived_not_registered(tmp_path):
    _, registry, _, _, result_service = services(tmp_path)
    average = result_service.seed_average("oct5k-man-0000", "V111", "all41")
    assert np.asarray(average["mean_px"]).shape == (3, 512)
    assert average["derived_rule"] == "seed_curve_mean_v1"
    assert average["tier"] is None
    assert len(average["source_result_ids"]) == 5
    assert not any("average" in item["result_id"] for item in registry.predictions)


def test_release_registry_contains_no_absolute_windows_paths():
    for path in (ROOT / "registry").rglob("*"):
        if path.is_file() and path.suffix in (".json", ".jsonl"):
            text = path.read_text(encoding="utf-8")
            assert "D:\\" not in text


def test_registry_degrades_cleanly_when_external_assets_are_absent(tmp_path):
    paths = AppPaths(
        app_root=tmp_path / "asset_free_app", workspace_root=WORKSPACE,
        registry=ROOT / "registry", state=tmp_path / "state",
        custom=tmp_path / "custom", trash=tmp_path / "trash", static=ROOT / "static",
    )
    paths.ensure_owned_dirs()
    registry = ReleaseRegistry(paths)
    db = CatalogueDB(paths.state / "catalogue.sqlite")
    catalogue = DatasetCatalogue(paths, registry, db)
    result_service = ResultService(registry, catalogue, db)
    assert len(registry.models) == 55
    assert len(registry.predictions) == 365
    assert registry.installed_model_ids == set()
    assert registry.installed_prediction_ids == set()
    assert result_service.list_for_scan("oct5k-man-0000")["available"] == 0

