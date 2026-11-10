from __future__ import annotations

import json
from collections import OrderedDict

import numpy as np

from .datasets import DatasetCatalogue
from .db import CatalogueDB
from .registry import ReleaseRegistry
from .util import sha256_file


class PackedArrayCache:
    def __init__(self, maximum: int = 4):
        self.maximum = maximum
        self.values: OrderedDict[str, dict[str, np.ndarray]] = OrderedDict()

    def get(self, result_id: str, registry: ReleaseRegistry) -> dict[str, np.ndarray]:
        if result_id in self.values:
            self.values.move_to_end(result_id)
            return self.values[result_id]
        entry = registry.prediction_by_id[result_id]
        path = registry.prediction_path(result_id)
        if sha256_file(path).lower() != entry["sha256"].lower():
            raise RuntimeError(f"prediction hash mismatch: {result_id}")
        with np.load(path, allow_pickle=False) as archive:
            arrays = {name: np.array(archive[name], copy=True) for name in archive.files}
        self.values[result_id] = arrays
        while len(self.values) > self.maximum:
            self.values.popitem(last=False)
        return arrays


class ResultService:
    def __init__(self, registry: ReleaseRegistry, catalogue: DatasetCatalogue, db: CatalogueDB):
        self.registry = registry
        self.catalogue = catalogue
        self.db = db
        self.cache = PackedArrayCache()

    def list_for_scan(self, scan_id: str, view: str | None = None) -> dict:
        scan = self.catalogue.get(scan_id)
        if scan["dataset"] == "custom":
            values = []
            for row in self.db.list_results(scan_id):
                model = self.registry.model_by_id.get(row["model_id"], {})
                values.append({
                    "result_id": f"custom::{scan_id}::{row['model_id']}",
                    "model_id": row["model_id"], "arm": model.get("arm"), "seed": model.get("seed"),
                    "category": model.get("category"), "role": model.get("role"),
                    "tier": "user_generated_exploratory", "view": "custom", "source": "generated",
                })
            return {"scan_id": scan_id, "view": "custom", "available": len(values), "results": values}

        positions = scan.get("prediction_positions", {})
        available_views = sorted(positions)
        if view is None:
            view = available_views[0] if available_views else None
        if view not in positions:
            return {"scan_id": scan_id, "view": view, "available": 0, "results": [], "views": available_views}
        installed = self.registry.predictions_by_dataset_view.get((scan["dataset"], view), [])
        if not installed:
            return {"scan_id": scan_id, "view": view, "available": 0, "results": [], "views": available_views}
        ok, message = self.catalogue.validate_pixels(scan_id)
        if not ok:
            return {
                "scan_id": scan_id, "view": view, "available": 0, "results": [],
                "views": available_views, "warning": message,
            }
        values = []
        for item in installed:
            model = self.registry.model_by_id[item["model_id"]]
            values.append({
                "result_id": item["result_id"], "model_id": item["model_id"],
                "arm": item["arm"], "seed": item["seed"], "category": model["category"],
                "role": model.get("role"), "tier": item["tier"], "view": view, "source": "supplied",
                "scale": model["scale"], "occlusion": model["occlusion"], "fda": model["fda"],
                "adaptation": model.get("adaptation"),
            })
        return {"scan_id": scan_id, "view": view, "available": len(values), "results": values, "views": available_views}

    def prediction(self, scan_id: str, result_id: str) -> dict:
        if result_id.startswith("custom::"):
            return self._custom_prediction(scan_id, result_id)
        scan = self.catalogue.get(scan_id)
        result = self.registry.prediction_by_id.get(result_id)
        if not result or result["dataset"] != scan["dataset"]:
            raise KeyError(result_id)
        position = scan.get("prediction_positions", {}).get(result["view"])
        if position is None:
            raise KeyError("prediction unavailable for scan")
        ok, message = self.catalogue.validate_pixels(scan_id)
        if not ok:
            raise ValueError(message)
        arrays = self.cache.get(result_id, self.registry)
        model = self.registry.model_by_id[result["model_id"]]
        return {
            "scan_id": scan_id, "result_id": result_id, "model_id": result["model_id"],
            "arm": result["arm"], "seed": result["seed"], "tier": result["tier"],
            "view": result["view"], "boundary_order": model["boundary_order"],
            "mean_px": arrays["mean_px"][position].astype(float).tolist(),
            "std_px": arrays["std_px"][position].astype(float).tolist(),
            "pixel_convention": "integer row is pixel centre; canvas uses x+0.5,y+0.5",
        }

    def seed_average(self, scan_id: str, arm: str, view: str) -> dict:
        scan = self.catalogue.get(scan_id)
        if scan["dataset"] == "custom":
            available = {row["model_id"]: row for row in self.db.list_results(scan_id)}
            result_ids = [f"custom::{scan_id}::{arm}__seed_{seed:03d}" for seed in range(5)]
            if not all(f"{arm}__seed_{seed:03d}" in available for seed in range(5)):
                raise KeyError("all five seed results are required")
        else:
            result_ids = [f"{scan['dataset']}__{view}__{arm}__seed_{seed:03d}" for seed in range(5)]
            if not all(result_id in self.registry.prediction_by_id for result_id in result_ids):
                raise KeyError("all five seed results are required")
        curves = [np.asarray(self.prediction(scan_id, result_id)["mean_px"], dtype=np.float64) for result_id in result_ids]
        average = np.stack(curves, axis=0).mean(axis=0, dtype=np.float64)
        return {
            "scan_id": scan_id, "arm": arm, "view": view,
            "derived_rule": "seed_curve_mean_v1", "label": "Average of 5 seeds, calculated by this viewer; not an evaluated model.",
            "boundary_order": ["ILM", "RPE_inner", "RPE_outer_BM"],
            "mean_px": average.tolist(), "source_result_ids": result_ids,
            "std_px": None, "tier": None,
        }

    def _custom_prediction(self, scan_id: str, result_id: str) -> dict:
        parts = result_id.split("::")
        if len(parts) != 3 or parts[1] != scan_id:
            raise KeyError(result_id)
        model_id = parts[2]
        rows = {row["model_id"]: row for row in self.db.list_results(scan_id)}
        if model_id not in rows:
            raise KeyError(result_id)
        row = rows[model_id]
        with np.load(row["result_path"], allow_pickle=False) as archive:
            mean = archive["mean_px"].astype(float).tolist()
            std = archive["std_px"].astype(float).tolist()
        model = self.registry.model_by_id[model_id]
        return {
            "scan_id": scan_id, "result_id": result_id, "model_id": model_id,
            "arm": model["arm"], "seed": model["seed"], "tier": "user_generated_exploratory",
            "view": "custom", "boundary_order": model["boundary_order"],
            "mean_px": mean, "std_px": std,
            "pixel_convention": "integer row is pixel centre; canvas uses x+0.5,y+0.5",
            "provenance": json.loads(row["provenance_json"]),
        }

