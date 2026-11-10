from __future__ import annotations

import os
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from .surface_model import SurfaceUNet, surfaces_from_logits
from .util import sha256_file


INFERENCE_VERSION = "custom_surface_inference_v1"
DUKE_AXIAL_UM = 3.24


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def percentile_normalize(image: np.ndarray) -> np.ndarray:
    array = image.astype(np.float32) / 255.0
    low, high = np.percentile(array, [0.5, 99.5])
    if high <= low:
        return np.zeros_like(array, dtype=np.float32)
    return np.clip((array - low) / (high - low), 0.0, 1.0).astype(np.float32)


def resize_height(image: np.ndarray, height: int) -> np.ndarray:
    if image.shape[0] == height:
        return np.asarray(image, dtype=np.float32)
    tensor = torch.from_numpy(np.ascontiguousarray(image, dtype=np.float32))[None, None]
    return F.interpolate(
        tensor, size=(height, image.shape[1]), mode="bilinear", align_corners=False,
        antialias=height < image.shape[0],
    )[0, 0].numpy()


def geometry(height: int, axial_um: float | None) -> tuple[int, str]:
    if axial_um is None:
        if height > 650:
            raise ValueError("axial spacing is required above 650 rows")
        return height, "uncalibrated_exploratory"
    target = int(round(height * axial_um / DUKE_AXIAL_UM))
    if target <= 0 or target > 2048:
        raise ValueError(f"calibrated model-input height {target} is outside the version-1 limit")
    return target, "calibrated"


@torch.inference_mode()
def infer_one(
    image_path: Path, checkpoint: Path, checkpoint_sha256: str,
    axial_um: float | None, lateral_um: float | None, device_name: str,
) -> tuple[np.ndarray, np.ndarray, dict]:
    if sha256_file(checkpoint).lower() != checkpoint_sha256.lower():
        raise RuntimeError("checkpoint hash mismatch")
    image = np.asarray(Image.open(image_path), dtype=np.uint8)
    if image.ndim != 2:
        raise ValueError("Custom canonical image is not 2-D")
    height, width = image.shape
    target_height, calibration = geometry(height, axial_um)
    prepared = resize_height(percentile_normalize(image), target_height)
    device = torch.device(device_name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    model = SurfaceUNet()
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    model.to(device).eval()
    tensor = torch.from_numpy(prepared)[None, None].to(device)
    with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
        logits = model(tensor)
        mean, std = surfaces_from_logits(logits)
    mean = mean[0].float().cpu().numpy()
    std = std[0].float().cpu().numpy()
    scale = height / target_height
    mean_native = ((mean + 0.5) * scale - 0.5).astype(np.float32)
    std_native = (std * scale).astype(np.float32)
    provenance = {
        "inference_version": INFERENCE_VERSION,
        "checkpoint_sha256": checkpoint_sha256,
        "device": str(device),
        "precision": "cuda_mixed" if device.type == "cuda" else "cpu_float32",
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "cudnn_version": torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else None,
        "python": platform.python_version(),
        "native_shape": [height, width],
        "model_shape": [target_height, width],
        "axial_um": axial_um,
        "lateral_um": lateral_um,
        "calibration": calibration,
        "height_in_observed_envelope": 512 <= target_height <= 619,
        "width_in_observed_envelope": 512 <= width <= 1024,
        "lateral_in_observed_range": None if lateral_um is None else 5.55 <= lateral_um <= 11.98,
        "pixel_convention": "integer row is pixel centre; inverse uses half-pixel mapping",
        "created_utc": utc_now(),
    }
    return mean_native, std_native, provenance


def atomic_npz(path: Path, **arrays) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".npz", dir=path.parent)
    os.close(fd)
    try:
        np.savez_compressed(temp_name, **arrays)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

