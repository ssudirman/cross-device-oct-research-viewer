"""Install the viewer's six public datasets from user-supplied archives.

The script never downloads or redistributes data. It extracts into a temporary
staging directory, validates the project layout, and only then moves completed
trees under oct_viewer/datasets. Existing non-empty dataset directories are
never overwritten.
"""

from __future__ import annotations

import argparse
import getpass
import json
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path, PurePosixPath

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from stage_oct5k_images import stage_images


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = APP_ROOT / "datasets"

ARCHIVES = {
    "duke_amd": ("Duke/AMD.zip", "Duke/Control.zip"),
    "duke_dme": ("Duke DME/2015_BOE_Chiu2.zip",),
    "jhu": ("JHU/OCT_Manual_Delineations-2018_June_29_b.zip",),
    "aroi": ("AROI/AROI.rar",),
    "oct5k": (
        "OCT5K/OCT5k.zip",
        "OCT5K/Macular-Dataset-R.Rasti_old.rar",
    ),
}

DESTINATIONS = (
    "oct5k_annotations", "oct5k_raw", "aroi", "duke_amd", "jhu", "duke_dme"
)


def safe_destination(root: Path, relative: PurePosixPath) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"unsafe archive member: {relative}")
    target = root.joinpath(*relative.parts).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"archive member escapes destination: {relative}") from exc
    return target


def extract_zip(
    archive: Path,
    destination: Path,
    *,
    strip_prefix: str | None = None,
    password: bytes | None = None,
) -> int:
    """Safely extract a ZIP, optionally removing one known outer directory."""
    destination.mkdir(parents=True, exist_ok=True)
    prefix = PurePosixPath(strip_prefix).parts if strip_prefix else ()
    written = 0
    with zipfile.ZipFile(archive) as handle:
        for member in handle.infolist():
            parts = PurePosixPath(member.filename.replace("\\", "/")).parts
            if prefix:
                if parts[: len(prefix)] != prefix:
                    raise RuntimeError(
                        f"unexpected member outside {strip_prefix!r} in {archive.name}: "
                        f"{member.filename}"
                    )
                parts = parts[len(prefix):]
            if not parts:
                continue
            target = safe_destination(destination, PurePosixPath(*parts))
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with handle.open(member, pwd=password) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
            except RuntimeError as exc:
                if member.flag_bits & 0x1:
                    raise RuntimeError(
                        f"could not decrypt {archive.name}; check the Rasti password"
                    ) from exc
                raise
            written += 1
    return written


def rar_command(archive: Path, destination: Path) -> list[str]:
    """Return a supported non-shell RAR extraction command."""
    destination.mkdir(parents=True, exist_ok=True)
    if shutil.which("7z"):
        return ["7z", "x", "-y", f"-o{destination}", str(archive)]
    if shutil.which("tar"):
        return ["tar", "-xf", str(archive), "-C", str(destination)]
    if shutil.which("unrar"):
        return ["unrar", "x", "-o+", str(archive), str(destination) + str(Path("/"))]
    raise RuntimeError(
        "RAR extraction requires 7-Zip, bsdtar/tar with RAR support, or unrar. "
        "Windows 10/11 normally provides a compatible tar.exe."
    )


def extract_rar(archive: Path, destination: Path) -> None:
    command = rar_command(archive, destination)
    completed = subprocess.run(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False
    )
    if completed.returncode:
        raise RuntimeError(
            f"RAR extraction failed for {archive.name} (exit {completed.returncode}): "
            f"{completed.stderr.strip()}"
        )


def require_archives(archive_root: Path) -> dict[str, list[Path]]:
    resolved: dict[str, list[Path]] = {}
    missing: list[str] = []
    for dataset, names in ARCHIVES.items():
        paths = [archive_root / Path(name) for name in names]
        resolved[dataset] = paths
        missing.extend(str(path) for path in paths if not path.is_file())
    if missing:
        raise FileNotFoundError("missing required archives:\n  " + "\n  ".join(missing))
    return resolved


def count_files(root: Path, suffix: str | None = None) -> int:
    return sum(
        1 for path in root.rglob("*")
        if path.is_file() and (suffix is None or path.suffix.lower() == suffix)
    )


def validate_layout(root: Path) -> dict:
    """Validate the exact project copies expected by the supplied registry."""
    checks = {
        "duke_amd_mat": count_files(root / "duke_amd" / "AMD", ".mat"),
        "duke_control_mat": count_files(root / "duke_amd" / "Control", ".mat"),
        "duke_dme_mat": count_files(root / "duke_dme", ".mat"),
        "jhu_vol": count_files(root / "jhu" / "vol", ".vol"),
        "jhu_delineation_mat": count_files(root / "jhu" / "delineation", ".mat"),
        "aroi_png": count_files(root / "aroi", ".png"),
        "oct5k_raw_images": (
            count_files(root / "oct5k_raw", ".tiff")
            + count_files(root / "oct5k_raw", ".png")
        ),
        "oct5k_manual_staged": count_files(
            root / "oct5k_annotations" / "Images" / "Images_Manual", ".png"
        ),
        "oct5k_automatic_staged": count_files(
            root / "oct5k_annotations" / "Images" / "Images_Automatic", ".png"
        ),
    }
    expected = {
        "duke_amd_mat": 269,
        "duke_control_mat": 115,
        "duke_dme_mat": 10,
        "jhu_vol": 35,
        "jhu_delineation_mat": 35,
        "aroi_png": 6780,
        "oct5k_raw_images": 4388,
        "oct5k_manual_staged": 1672,
        "oct5k_automatic_staged": 2562,
    }
    failures = {
        key: {"expected": expected[key], "observed": value}
        for key, value in checks.items() if value != expected[key]
    }
    report = {"ok": not failures, "counts": checks, "failures": failures}
    if failures:
        raise RuntimeError("dataset validation failed:\n" + json.dumps(report, indent=2))
    return report


def ensure_installable(target_root: Path) -> None:
    occupied = []
    for name in DESTINATIONS:
        path = target_root / name
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            occupied.append(str(path))
    if occupied:
        raise RuntimeError(
            "refusing to overwrite existing dataset directories; use --verify-only or "
            "move them aside first:\n  " + "\n  ".join(occupied)
        )


def install(archive_root: Path, target_root: Path) -> dict:
    archives = require_archives(archive_root)
    target_root.mkdir(parents=True, exist_ok=True)
    ensure_installable(target_root)
    staging = target_root / f".install-staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        # Do the password-gated OCT5K extraction first, before the 18 GB Duke
        # archives, so a mistyped password fails early and cheaply.
        print("Extracting OCT5K Rasti raw archive ...", flush=True)
        rasti_unpack = staging / "_rasti_unpack"
        extract_rar(archives["oct5k"][1], rasti_unpack)
        nested_zips = sorted(rasti_unpack.glob("Macular-Dataset-R.Rasti-part*.zip"))
        if len(nested_zips) != 4:
            raise RuntimeError("expected four nested Rasti ZIP files")
        password = getpass.getpass(
            "Password for the four Rasti ZIP files (input is hidden): "
        ).encode("utf-8")
        raw_root = staging / "oct5k_raw"
        for nested in nested_zips:
            print(f"  extracting {nested.name} ...", flush=True)
            extract_zip(nested, raw_root, password=password)
        shutil.rmtree(rasti_unpack)

        print("Extracting OCT5K annotations ...", flush=True)
        extract_zip(
            archives["oct5k"][0], staging / "oct5k_annotations", strip_prefix="OCT5k"
        )

        print("Staging viewer-ready OCT5K images ...", flush=True)
        scripts = staging / "oct5k_annotations" / "Scripts" / "paths"
        manual = stage_images(
            raw_root, staging / "oct5k_annotations", scripts / "manual_paths.csv"
        )
        automatic = stage_images(
            raw_root, staging / "oct5k_annotations", scripts / "automatic_paths.csv"
        )
        print(f"  manual: {manual}")
        print(f"  automatic: {automatic}")

        print("Extracting AROI ...", flush=True)
        aroi_unpack = staging / "_aroi_unpack"
        extract_rar(archives["aroi"][0], aroi_unpack)
        aroi_source = aroi_unpack / "AROI - online"
        if not aroi_source.is_dir():
            raise RuntimeError("AROI.rar did not contain the expected 'AROI - online' root")
        shutil.move(str(aroi_source), str(staging / "aroi"))
        shutil.rmtree(aroi_unpack)

        print("Extracting JHU HC/MS ...", flush=True)
        extract_zip(
            archives["jhu"][0], staging / "jhu",
            strip_prefix="OCT_Manual_Delineations-2018_June_29",
        )

        print("Extracting Duke DME ...", flush=True)
        extract_zip(
            archives["duke_dme"][0], staging / "duke_dme", strip_prefix="2015_BOE_Chiu"
        )

        print("Extracting Duke AMD/control ...", flush=True)
        extract_zip(archives["duke_amd"][0], staging / "duke_amd")
        extract_zip(archives["duke_amd"][1], staging / "duke_amd")

        report = validate_layout(staging)
        for name in DESTINATIONS:
            destination = target_root / name
            if destination.exists():
                destination.rmdir()  # permitted only because ensure_installable found it empty
            shutil.move(str(staging / name), str(destination))
        custom = target_root / "custom_dataset" / "scans"
        custom.mkdir(parents=True, exist_ok=True)
        report["target_root"] = str(target_root.resolve())
        report["custom_dataset"] = str(custom.parent.resolve())
        return report
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    finally:
        if staging.exists() and not any(staging.iterdir()):
            staging.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the OCT viewer datasets from already downloaded archives."
    )
    parser.add_argument(
        "--archive-root", type=Path,
        default=None,
        help="folder containing Duke/, Duke DME/, JHU/, AROI/, and OCT5K/",
    )
    parser.add_argument(
        "--target-root", type=Path, default=DEFAULT_TARGET,
        help="destination corresponding to oct_viewer/datasets",
    )
    parser.add_argument(
        "--verify-only", action="store_true",
        help="validate an existing target layout without extracting anything",
    )
    args = parser.parse_args()
    try:
        if args.verify_only:
            report = validate_layout(args.target_root.resolve())
        else:
            if args.archive_root is None:
                parser.error("--archive-root is required unless --verify-only is used")
            report = install(args.archive_root.resolve(), args.target_root.resolve())
        print(json.dumps(report, indent=2))
        return 0
    except (FileNotFoundError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
