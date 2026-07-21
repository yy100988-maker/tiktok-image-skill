from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

from config import CONFIG_NAME, apply_config_file, find_config_file, load_config_file


def ask(label: str, current: str = "", secret: bool = False) -> str:
    prompt = f"{label} [{current}]: " if current else f"{label}: "
    value = getpass.getpass(prompt) if secret else input(prompt)
    return value.strip() or current


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure the image skill")
    parser.add_argument("--config-file", type=Path, help="Path to the JSON configuration file")
    args = parser.parse_args()
    config_path = args.config_file or find_config_file() or (Path(__file__).resolve().parents[1] / CONFIG_NAME)
    current = load_config_file(config_path)
    values = {
        "IMG_BASE_URL": ask("Vetech AI 服务地址（向服务方获取）", str(current.get("IMG_BASE_URL", ""))),
        "IMG_MODEL": ask("Image model", str(current.get("IMG_MODEL", "gpt-image-2"))),
        "IMG_API_KEY": ask("VTeTech API key", str(current.get("IMG_API_KEY", "")), secret=True),
        "IMAGE_OUTPUT_ROOT": ask("Single image output root", str(current.get("IMAGE_OUTPUT_ROOT", "output"))),
        "EXCEL_OUTPUT_ROOT": ask("Excel batch output root", str(current.get("EXCEL_OUTPUT_ROOT", "excel-output"))),
        "COS_BUCKET_URL": ask("COS bucket URL", str(current.get("COS_BUCKET_URL", ""))),
        "COS_UPLOAD_PREFIX": ask("COS upload prefix", str(current.get("COS_UPLOAD_PREFIX", "image"))),
        "REFERENCE_IMAGE_MODE": ask("Reference image mode (base64/cos)", str(current.get("REFERENCE_IMAGE_MODE", "base64"))),
    }
    if values["IMG_API_KEY"]:
        values["API_KEY"] = values["IMG_API_KEY"]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved configuration: {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
