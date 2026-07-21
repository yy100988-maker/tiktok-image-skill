from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


CONFIG_NAME = "image-config.json"
CONFIG_KEYS = {
    "IMG_BASE_URL",
    "IMG_MODEL",
    "IMG_API_KEY",
    "API_KEY",
    "IMAGE_OUTPUT_ROOT",
    "EXCEL_OUTPUT_ROOT",
    "COS_BUCKET_URL",
    "COS_UPLOAD_PREFIX",
    "REFERENCE_IMAGE_MODE",
}


def find_config_file(explicit: str | Path | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    env_path = os.environ.get("IMAGE_CONFIG_FILE", "").strip()
    if env_path:
        path = Path(env_path).expanduser()
        if path.is_file():
            return path
    for directory in (Path.cwd(), *Path.cwd().parents):
        path = directory / CONFIG_NAME
        if path.is_file():
            return path
    path = Path(__file__).resolve().parents[1] / CONFIG_NAME
    return path if path.is_file() else None


def load_config_file(explicit: str | Path | None = None) -> dict[str, Any]:
    path = find_config_file(explicit)
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_config_file(explicit: str | Path | None = None) -> Path | None:
    path = find_config_file(explicit)
    for key, value in load_config_file(explicit).items():
        if key in CONFIG_KEYS and value is not None and not os.environ.get(key, "").strip():
            os.environ[key] = str(value)
    return path
