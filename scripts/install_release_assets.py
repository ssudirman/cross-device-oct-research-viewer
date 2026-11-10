"""Download, verify and install the versioned model/prediction archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


APP_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = APP_ROOT / "registry" / "release_assets.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def progress(done: int, total: int) -> str:
    fraction = 0 if not total else done / total
    return f"{done / 2**20:,.0f}/{total / 2**20:,.0f} MiB ({fraction:.0%})"


def download(url: str, destination: Path, expected_bytes: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    offset = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(url, headers={"User-Agent": "oct-viewer-asset-installer/1.0"})
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as exc:
        if offset and exc.code == 416 and offset == expected_bytes:
            os.replace(partial, destination)
            return
        raise
    status = getattr(response, "status", response.getcode())
    mode = "ab" if offset and status == 206 else "wb"
    if mode == "wb":
        offset = 0
    done = offset
    next_report = done
    with response, partial.open(mode) as target:
        while True:
            chunk = response.read(4 * 1024 * 1024)
            if not chunk:
                break
            target.write(chunk)
            done += len(chunk)
            if done >= next_report:
                print(f"    {progress(done, expected_bytes)}", flush=True)
                next_report = done + 128 * 1024 * 1024
    if done != expected_bytes:
        raise RuntimeError(f"downloaded size is {done}, expected {expected_bytes}")
    os.replace(partial, destination)


def safe_target(root: Path, archive_name: str) -> Path:
    relative = PurePosixPath(archive_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"unsafe archive member: {archive_name}")
    target = root.joinpath(*relative.parts).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"archive member escapes application root: {archive_name}") from exc
    return target


def install_archive(archive_path: Path, package: dict, target_root: Path) -> None:
    expected = {item["path"]: item for item in package["members"]}
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if names != list(expected):
            raise RuntimeError(f"unexpected file list in {archive_path.name}")
        for number, info in enumerate(archive.infolist(), 1):
            item = expected[info.filename]
            if info.file_size != item["bytes"]:
                raise RuntimeError(f"stored size mismatch for {info.filename}")
            target = safe_target(target_root, info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=target.name, suffix=".partial", dir=target.parent)
            os.close(fd)
            temp = Path(temp_name)
            try:
                with archive.open(info) as source, temp.open("wb") as output:
                    shutil.copyfileobj(source, output, length=4 * 1024 * 1024)
                if sha256(temp) != item["sha256"]:
                    raise RuntimeError(f"extracted SHA-256 mismatch: {info.filename}")
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
            if number % 20 == 0 or number == len(names):
                print(f"    installed {number}/{len(names)} files", flush=True)


def verify_installed(packages: list[dict], target_root: Path) -> bool:
    okay = True
    for package in packages:
        missing = invalid = 0
        for item in package["members"]:
            path = target_root / item["path"]
            if not path.is_file():
                missing += 1
            elif path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
                invalid += 1
        label = "OK" if not missing and not invalid else "INCOMPLETE"
        print(f"{package['id']}: {label} ({len(package['members']) - missing - invalid}/{len(package['members'])}; missing={missing}; invalid={invalid})")
        okay &= not missing and not invalid
    return okay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="use local archives instead of downloading from Zenodo")
    parser.add_argument("--target", type=Path, default=APP_ROOT, help="oct_viewer application root")
    parser.add_argument("--verify-only", action="store_true", help="verify installed files without downloading")
    parser.add_argument("--package", action="append", dest="packages", help="install only this package ID; repeat as needed")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    package_by_id = {item["id"]: item for item in manifest["packages"]}
    selected_ids = args.packages or manifest["default_install"]
    unknown = sorted(set(selected_ids) - set(package_by_id))
    if unknown:
        parser.error(f"unknown package IDs: {unknown}")
    packages = [package_by_id[item] for item in selected_ids]
    target_root = args.target.resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    if args.verify_only:
        return 0 if verify_installed(packages, target_root) else 1

    cache = target_root / ".asset_downloads"
    for package in packages:
        if args.source_dir:
            archive_path = args.source_dir.resolve() / package["filename"]
            if not archive_path.is_file():
                raise RuntimeError(f"local archive is missing: {archive_path}")
        else:
            archive_path = cache / package["filename"]
            if not archive_path.is_file() or archive_path.stat().st_size != package["bytes"] or sha256(archive_path) != package["sha256"]:
                print(f"Downloading {package['filename']}...", flush=True)
                download(package["url"], archive_path, package["bytes"])
        print(f"Verifying {package['filename']}...", flush=True)
        if archive_path.stat().st_size != package["bytes"] or sha256(archive_path) != package["sha256"]:
            raise RuntimeError(f"archive SHA-256 mismatch: {package['filename']}")
        print(f"Installing {package['id']}...", flush=True)
        install_archive(archive_path, package, target_root)
    if not verify_installed(packages, target_root):
        raise RuntimeError("installed-asset verification failed")
    print("All selected release assets are installed and verified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
