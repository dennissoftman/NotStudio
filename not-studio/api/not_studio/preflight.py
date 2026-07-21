"""Read-only readiness checks for the local end-to-end generation stack."""

from __future__ import annotations

import importlib.util
import json
import platform
import shutil
from typing import Any

import psutil

from .config import get_settings


def collect_preflight() -> dict[str, Any]:
    settings = get_settings()
    disk = shutil.disk_usage(settings.data_dir)
    checks: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "system_ram_gib": round(psutil.virtual_memory().total / 1024**3, 1),
        "data_dir": str(settings.data_dir),
        "free_disk_gib": round(disk.free / 1024**3, 1),
        "planner_model": settings.planner_model,
        "music_model": "ACE-Step 1.5",
        "image_model": settings.image_model,
        "imports": {
            name: importlib.util.find_spec(name) is not None
            for name in ("torch", "outlines", "diffusers", "transformers", "acestep")
        },
        "cuda": {"available": False},
    }
    if checks["imports"]["torch"]:
        import torch

        checks["cuda"]["available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            checks["cuda"].update(
                {
                    "device": props.name,
                    "vram_gib": round(props.total_memory / 1024**3, 1),
                    "torch_cuda": torch.version.cuda,
                    "bf16_supported": torch.cuda.is_bf16_supported(),
                }
            )
    required_imports = all(checks["imports"].values())
    checks["ready"] = bool(
        required_imports
        and checks["cuda"]["available"]
        and checks["cuda"].get("vram_gib", 0) >= 12
        and checks["free_disk_gib"] >= 35
    )
    checks["recommendations"] = []
    if checks["free_disk_gib"] < 35:
        checks["recommendations"].append(
            "Free at least 35 GiB for model caches and generated media"
        )
    if not checks["cuda"]["available"]:
        checks["recommendations"].append("Run generation on an NVIDIA CUDA host")
    if checks["cuda"].get("vram_gib", 0) < 12:
        checks["recommendations"].append("At least 12 GiB VRAM is required; 16 GiB is recommended")
    missing = [name for name, available in checks["imports"].items() if not available]
    if missing:
        checks["recommendations"].append(
            "Install missing packages with uv sync: " + ", ".join(missing)
        )
    return checks


def main() -> None:
    result = collect_preflight()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ready"] else 1)


if __name__ == "__main__":
    main()
