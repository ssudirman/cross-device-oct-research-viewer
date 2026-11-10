from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .config import AppPaths
from .util import sha256_file


class ReleaseRegistry:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        manifest_path = paths.registry / "release_manifest.json"
        if not manifest_path.exists():
            raise RuntimeError(
                "Required application metadata is missing. Restore the supplied registry folder "
                "or reinstall the application package."
            )
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self._validate_component("models")
        self._validate_component("predictions")
        model_doc = json.loads((paths.registry / self.manifest["models"]["path"]).read_text(encoding="utf-8"))
        prediction_doc = json.loads((paths.registry / self.manifest["predictions"]["path"]).read_text(encoding="utf-8"))
        self.models = model_doc["models"]
        self.predictions = prediction_doc["predictions"]
        if len(self.models) != 55 or len(self.predictions) != 365:
            raise RuntimeError("registry count mismatch")
        self.model_by_id = {item["model_id"]: item for item in self.models}
        self.prediction_by_id = {item["result_id"]: item for item in self.predictions}
        for item in self.models:
            item["installed"] = (paths.app_root / item["checkpoint"]).is_file()
        for item in self.predictions:
            item["installed"] = (paths.app_root / item["path"]).is_file()
        self.installed_model_ids = {
            item["model_id"] for item in self.models if item["installed"]
        }
        self.installed_prediction_ids = {
            item["result_id"] for item in self.predictions if item["installed"]
        }
        self.predictions_by_dataset_view: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for item in self.predictions:
            if item["installed"]:
                self.predictions_by_dataset_view[(item["dataset"], item["view"])].append(item)
        for values in self.predictions_by_dataset_view.values():
            values.sort(key=lambda item: (item["arm"], item["seed"]))

    def _validate_component(self, name: str) -> None:
        record = self.manifest[name]
        path = self.paths.registry / record["path"]
        if sha256_file(path).lower() != record["sha256"].lower():
            raise RuntimeError(f"release registry hash mismatch: {path.name}")

    def checkpoint_path(self, model_id: str) -> Path:
        model = self.model_by_id[model_id]
        path = (self.paths.app_root / model["checkpoint"]).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"model asset is not installed: {model_id}")
        return path

    def prediction_path(self, result_id: str) -> Path:
        result = self.prediction_by_id[result_id]
        path = (self.paths.app_root / result["path"]).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"prediction asset is not installed: {result_id}")
        return path


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows

