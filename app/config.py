from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = APP_ROOT.parent

DEFAULT_DATASET_ROOTS = {
    "oct5k_annotations": "datasets/oct5k_annotations",
    "oct5k_raw": "datasets/oct5k_raw",
    "aroi": "datasets/aroi",
    "duke_amd": "datasets/duke_amd",
    "jhu": "datasets/jhu",
    "duke_dme": "datasets/duke_dme",
}


@dataclass(frozen=True)
class AppPaths:
    app_root: Path
    workspace_root: Path
    registry: Path
    state: Path
    custom: Path
    trash: Path
    static: Path

    @classmethod
    def discover(cls) -> "AppPaths":
        workspace = Path(os.environ.get("OCT_VIEWER_WORKSPACE", DEFAULT_WORKSPACE)).resolve()
        state = Path(os.environ.get("OCT_VIEWER_STATE", APP_ROOT / "state")).resolve()
        custom_value = os.environ.get("OCT_VIEWER_CUSTOM")
        if custom_value is None:
            custom_value = "datasets/custom_dataset"
            saved_path = state / "settings.json"
            if saved_path.exists():
                saved = json.loads(saved_path.read_text(encoding="utf-8"))
                custom_value = saved.get("custom_dataset_root", custom_value)
        custom = Path(custom_value).expanduser()
        if not custom.is_absolute():
            custom = APP_ROOT / custom
        custom = custom.resolve()
        return cls(
            app_root=APP_ROOT,
            workspace_root=workspace,
            registry=(APP_ROOT / "registry").resolve(),
            state=state,
            custom=custom,
            trash=(APP_ROOT / "trash").resolve(),
            static=(APP_ROOT / "static").resolve(),
        )

    def ensure_owned_dirs(self) -> None:
        for path in (self.registry, self.state, self.custom, self.trash):
            path.mkdir(parents=True, exist_ok=True)
        (self.state / "jobs").mkdir(parents=True, exist_ok=True)
        (self.custom / "scans").mkdir(parents=True, exist_ok=True)


def default_dataset_roots() -> dict[str, str]:
    """Return portable paths stored relative to the oct_viewer root."""
    return dict(DEFAULT_DATASET_ROOTS)


def resolve_dataset_root(paths: AppPaths, value: str) -> Path:
    """Resolve a stored dataset path, anchoring relative values at oct_viewer/."""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = paths.app_root / candidate
    return candidate.resolve()


def portable_dataset_root(paths: AppPaths, value: str) -> str:
    """Store app-local roots portably; retain absolute external roots if selected."""
    resolved = resolve_dataset_root(paths, value)
    try:
        return resolved.relative_to(paths.app_root).as_posix()
    except ValueError:
        return str(resolved)


def settings_path(paths: AppPaths) -> Path:
    return paths.state / "settings.json"


def load_settings(paths: AppPaths) -> dict:
    base = {
        "dataset_roots": default_dataset_roots(),
        "custom_dataset_root": "datasets/custom_dataset",
        "notice_accepted": False,
    }
    path = settings_path(paths)
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        base.update({k: v for k, v in saved.items() if k != "dataset_roots"})
        base["dataset_roots"].update(saved.get("dataset_roots", {}))
    return base


def save_settings(paths: AppPaths, settings: dict) -> None:
    from .util import atomic_json
    atomic_json(settings_path(paths), settings)

