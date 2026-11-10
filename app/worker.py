from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from .config import AppPaths
from .db import CatalogueDB
from .inference import atomic_npz, infer_one, utc_now
from .registry import ReleaseRegistry
from .util import atomic_json, sha256_file


def run(job_path: Path) -> int:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    paths = AppPaths.discover()
    paths.ensure_owned_dirs()
    registry = ReleaseRegistry(paths)
    db = CatalogueDB(paths.state / "catalogue.sqlite")
    scan = db.get_custom(job["scan_id"])
    if not scan:
        raise RuntimeError("Custom scan not found")
    job["state"] = "running"
    job["started_utc"] = utc_now()
    atomic_json(job_path, job)
    failures = []
    for index, model_id in enumerate(job["model_ids"]):
        job["current_model"] = model_id
        job["completed"] = index
        atomic_json(job_path, job)
        model = registry.model_by_id[model_id]
        output = Path(scan["canonical_path"]).parent / "results" / f"{model_id}.npz"
        existing = {row["model_id"]: row for row in db.list_results(scan["scan_id"])}
        if model_id in existing and Path(existing[model_id]["result_path"]).exists():
            continue
        try:
            mean, std, provenance = infer_one(
                Path(scan["canonical_path"]), registry.checkpoint_path(model_id),
                model["checkpoint_sha256"], scan["axial_um"], scan["lateral_um"], job["device"],
            )
            provenance.update({
                "scan_id": scan["scan_id"], "pixel_sha256": scan["pixel_sha256"],
                "model_id": model_id, "arm": model["arm"], "seed": model["seed"],
                "provenance_class": "user_generated_exploratory",
            })
            atomic_npz(output, mean_px=mean, std_px=std)
            db.upsert_result({
                "scan_id": scan["scan_id"], "model_id": model_id, "result_path": str(output),
                "result_sha256": sha256_file(output), "provenance": provenance, "created_utc": provenance["created_utc"],
            })
        except Exception as exc:
            failures.append({"model_id": model_id, "error": str(exc), "traceback": traceback.format_exc()})
    job["completed"] = len(job["model_ids"])
    job["current_model"] = None
    job["failures"] = failures
    job["state"] = "completed_with_failures" if failures else "completed"
    job["finished_utc"] = utc_now()
    atomic_json(job_path, job)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args()
    return run(args.job.resolve())


if __name__ == "__main__":
    raise SystemExit(main())

