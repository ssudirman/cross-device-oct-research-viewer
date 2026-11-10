from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_study_results_payload_contains_frozen_values():
    payload = json.loads((ROOT / "results" / "study_results.json").read_text(encoding="utf-8"))
    assert payload["selection"]["R_star"] == "V111"
    assert payload["selection"]["C_star"] == "V100"
    scores = {item["arm"]: item["score"] for item in payload["selection"]["scores"]}
    assert abs(scores["V111"] - 0.43924310051012455) < 1e-12

    confirmatory = {item["id"]: item for item in payload["confirmatory"]["datasets"]}
    jhu_h1 = confirmatory["jhu"]["contrasts"][0]
    dme_h1 = confirmatory["dme"]["contrasts"][0]
    assert abs(jhu_h1["difference"] - (-5.431331888381456)) < 1e-12
    assert abs(dme_h1["difference"] - (-125.27035141976647)) < 1e-12


def test_analysis_asset_manifest_hashes_every_packaged_source():
    manifest = json.loads((ROOT / "results" / "provenance" / "analysis_assets.json").read_text(encoding="utf-8"))
    assert len(manifest["assets"]) == 23
    for asset in manifest["assets"]:
        path = ROOT / asset["path"]
        assert path.is_file()
        assert path.stat().st_size == asset["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
    results_path = ROOT / "results" / "study_results.json"
    assert hashlib.sha256(results_path.read_bytes()).hexdigest() == manifest["study_results_sha256"]


def test_branding_and_required_background_colour_are_present():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    assert "Liverpool John Moores University Research" in html
    assert "Cross-Device OCT Research" in html
    assert "AMD OCT research workspace" not in html
    assert "Boundary inference viewer" not in html
    assert "--bg: #13387e" in css
    assert "background-color: #13387e" in css


def test_dashboard_uses_local_svg_and_no_external_runtime():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="studyResultsWorkspace"' in html
    assert "<svg" in script
    assert "plotly" not in (html + script).lower()
    assert "https://" not in html


def test_download_endpoint_is_manifest_allowlisted():
    from app.main import download_study_result

    with pytest.raises(HTTPException) as error:
        download_study_result("../../outside")
    assert error.value.status_code == 404

    manifest = json.loads((ROOT / "results" / "provenance" / "analysis_assets.json").read_text(encoding="utf-8"))
    response = download_study_result(manifest["assets"][0]["id"])
    assert Path(response.path).is_file()
    assert (ROOT / "results").resolve() in Path(response.path).resolve().parents
