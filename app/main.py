from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import AppPaths, load_settings, portable_dataset_root, resolve_dataset_root, save_settings
from .custom import CustomService, canonicalize_upload, utc_now
from .datasets import DatasetCatalogue
from .db import CatalogueDB
from .registry import ReleaseRegistry
from .results import ResultService
from .util import atomic_json, image_png_bytes


NOTICE = (
    "For research use only. Not for clinical diagnosis, treatment, or patient management. "
    "Predictions may be wrong, especially on devices, image formats, or anatomy outside the evaluated data."
)

paths = AppPaths.discover()
paths.ensure_owned_dirs()
db = CatalogueDB(paths.state / "catalogue.sqlite")
registry = ReleaseRegistry(paths)
catalogue = DatasetCatalogue(paths, registry, db)
results = ResultService(registry, catalogue, db)
custom = CustomService(paths, db, catalogue)

app = FastAPI(title="Cross-Device OCT Research", version="0.2.0")
app.mount("/static", StaticFiles(directory=paths.static), name="static")


class AddToCustomRequest(BaseModel):
    orientation_confirmed: bool


class InferenceRequest(BaseModel):
    model_ids: list[str] | None = None
    device: str = "cpu"


class DatasetRootsRequest(BaseModel):
    dataset_roots: dict[str, str]


@app.get("/", response_class=HTMLResponse)
def root():
    return (paths.static / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def status():
    models_installed = len(registry.installed_model_ids)
    predictions_installed = len(registry.installed_prediction_ids)
    return {
        "application": "Cross-Device OCT Research", "version": app.version,
        "notice": NOTICE, "models": models_installed, "predictions": predictions_installed,
        "models_registered": len(registry.models), "predictions_registered": len(registry.predictions),
        "assets_complete": models_installed == len(registry.models) and predictions_installed == len(registry.predictions),
        "asset_doi": "10.5281/zenodo.24109134",
        "deployment": "local_single_user", "workspace": str(paths.workspace_root),
    }


@app.get("/api/study-results")
def study_results():
    path = paths.app_root / "results" / "study_results.json"
    if not path.exists():
        raise HTTPException(503, "study results have not been built")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/study-results/files")
def study_result_files():
    path = paths.app_root / "results" / "provenance" / "analysis_assets.json"
    if not path.exists():
        raise HTTPException(503, "study-results manifest is missing")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/study-results/download/{asset_id}")
def download_study_result(asset_id: str):
    manifest_path = paths.app_root / "results" / "provenance" / "analysis_assets.json"
    if not manifest_path.exists():
        raise HTTPException(503, "study-results manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset = next((item for item in manifest["assets"] if item["id"] == asset_id), None)
    if not asset:
        raise HTTPException(404, "unknown analysis asset")
    requested = (paths.app_root / asset["path"]).resolve()
    allowed_root = (paths.app_root / "results").resolve()
    if allowed_root not in requested.parents or not requested.is_file():
        raise HTTPException(404, "analysis asset is unavailable")
    return FileResponse(requested, filename=requested.name, media_type="application/octet-stream")


@app.get("/api/models")
def list_models():
    return {"models": registry.models}


@app.get("/api/settings/dataset-roots")
def get_dataset_roots():
    return {
        "dataset_roots": dict(catalogue.settings["dataset_roots"]),
        "custom_dataset_root": catalogue.settings["custom_dataset_root"],
    }


@app.put("/api/settings/dataset-roots")
def update_dataset_roots(request: DatasetRootsRequest):
    allowed = {"oct5k_annotations", "oct5k_raw", "aroi", "duke_amd", "jhu", "duke_dme"}
    if set(request.dataset_roots) != allowed:
        raise HTTPException(422, f"dataset_roots must contain exactly {sorted(allowed)}")
    stored = {key: portable_dataset_root(paths, value) for key, value in request.dataset_roots.items()}
    settings = load_settings(paths)
    settings["dataset_roots"] = stored
    save_settings(paths, settings)
    catalogue.settings = settings
    catalogue.roots = {key: resolve_dataset_root(paths, value) for key, value in stored.items()}
    catalogue._pixel_validation.clear()
    return {"dataset_roots": stored, "datasets": catalogue.datasets()}


@app.get("/api/datasets")
def list_datasets():
    return {"datasets": catalogue.datasets()}


@app.get("/api/datasets/{dataset}/groups")
def list_groups(dataset: str):
    if dataset not in catalogue.rows and dataset != "custom":
        raise HTTPException(404, "unknown dataset")
    return {"dataset": dataset, "groups": catalogue.groups(dataset)}


@app.get("/api/datasets/{dataset}/scans")
def list_scans(
    dataset: str, group: str | None = None, search: str | None = None,
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
):
    if dataset not in catalogue.rows and dataset != "custom":
        raise HTTPException(404, "unknown dataset")
    return catalogue.list_scans(dataset, group, search, offset, limit)


@app.get("/api/scans/{scan_id}")
def get_scan(scan_id: str):
    try:
        scan = catalogue.get(scan_id)
        return catalogue.public_scan(scan) if scan["dataset"] != "custom" else scan
    except KeyError:
        raise HTTPException(404, "scan not found") from None


@app.get("/api/scans/{scan_id}/image")
def get_image(scan_id: str):
    try:
        image = catalogue.load_image(scan_id)
    except KeyError:
        raise HTTPException(404, "scan not found") from None
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(image_png_bytes(image), media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/scans/{scan_id}/results")
def list_results(scan_id: str, view: str | None = None):
    try:
        return results.list_for_scan(scan_id, view)
    except KeyError:
        raise HTTPException(404, "scan not found") from None


@app.get("/api/scans/{scan_id}/predictions/{result_id}")
def get_prediction(scan_id: str, result_id: str):
    try:
        return results.prediction(scan_id, result_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/scans/{scan_id}/seed-average/{arm}")
def get_seed_average(scan_id: str, arm: str, view: str):
    try:
        return results.seed_average(scan_id, arm, view)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from None


@app.post("/api/custom/import")
async def import_custom(
    file: UploadFile = File(...),
    orientation_confirmed: bool = Form(...),
    confirm_16bit: bool = Form(False),
    axial_um: float | None = Form(None),
    lateral_um: float | None = Form(None),
    spacing_provenance: str | None = Form(None),
):
    data = await file.read()
    try:
        scan, created = custom.register_upload(
            data, file.filename or "upload", orientation_confirmed, confirm_16bit,
            axial_um, lateral_um, spacing_provenance,
        )
        return {"created": created, "scan": scan}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/custom/preview")
async def preview_custom(file: UploadFile = File(...), confirm_16bit: bool = Form(False)):
    data = await file.read()
    try:
        image, _ = canonicalize_upload(data, file.filename or "upload", confirm_16bit)
        return Response(image_png_bytes(image), media_type="image/png", headers={"Cache-Control": "no-store"})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/scans/{scan_id}/add-to-custom")
def add_to_custom(scan_id: str, request: AddToCustomRequest):
    try:
        scan, created = custom.add_builtin(scan_id, request.orientation_confirmed)
        return {"created": created, "scan": scan}
    except KeyError:
        raise HTTPException(404, "scan not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.delete("/api/custom/{scan_id}")
def trash_custom(scan_id: str):
    try:
        custom.trash(scan_id)
        return {"scan_id": scan_id, "state": "trashed"}
    except KeyError:
        raise HTTPException(404, "Custom scan not found") from None


@app.post("/api/custom/{scan_id}/inference")
def start_inference(scan_id: str, request: InferenceRequest):
    if not db.get_custom(scan_id):
        raise HTTPException(404, "Custom scan not found")
    if request.device != "cpu" and not request.device.startswith("cuda:"):
        raise HTTPException(422, "device must be cpu or cuda:N")
    model_ids = request.model_ids or sorted(registry.installed_model_ids)
    unknown = sorted(set(model_ids) - set(registry.model_by_id))
    if unknown:
        raise HTTPException(422, f"unknown model IDs: {unknown}")
    unavailable = sorted(set(model_ids) - registry.installed_model_ids)
    if unavailable:
        raise HTTPException(409, f"model assets are not installed: {unavailable}")
    if not model_ids:
        raise HTTPException(409, "no model assets are installed; run scripts/install_release_assets.py")
    job_id = f"job-{uuid.uuid4().hex}"
    now = utc_now()
    job_path = paths.state / "jobs" / f"{job_id}.json"
    job = {
        "schema": 1, "job_id": job_id, "scan_id": scan_id, "model_ids": model_ids,
        "device": request.device, "state": "queued", "completed": 0, "current_model": None,
        "created_utc": now, "research_use_only": True,
    }
    atomic_json(job_path, job)
    db.insert_job({
        "job_id": job_id, "scan_id": scan_id, "state": "queued", "job_path": str(job_path),
        "created_utc": now, "updated_utc": now,
    })
    env = os.environ.copy()
    env["OCT_VIEWER_WORKSPACE"] = str(paths.workspace_root)
    env["OCT_VIEWER_STATE"] = str(paths.state)
    env["OCT_VIEWER_CUSTOM"] = str(paths.custom)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        [sys.executable, "-I", "-B", str(paths.app_root / "worker_entry.py"), "--job", str(job_path)],
        cwd=str(paths.app_root), env=env, creationflags=creationflags,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return job


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    row = db.get_job(job_id)
    if not row:
        raise HTTPException(404, "job not found")
    path = Path(row["job_path"])
    if not path.exists():
        raise HTTPException(500, "job state file is missing")
    return json.loads(path.read_text(encoding="utf-8"))

