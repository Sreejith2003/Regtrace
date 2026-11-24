from __future__ import annotations

from pathlib import Path

import yaml

from regtrace.regulations.models import Pack

PACK_FILE = "pack.yaml"
OBLIGATIONS_FILE = "obligations.yaml"


def load_pack(folder: str | Path) -> Pack:
    """Load `pack.yaml` and `obligations.yaml` from a pack folder."""
    folder = Path(folder)
    pack_file = folder / PACK_FILE
    if not pack_file.is_file():
        raise FileNotFoundError(f"No {PACK_FILE} in {folder}")
    data = _read_yaml(pack_file)
    obligations_file = folder / OBLIGATIONS_FILE
    if obligations_file.is_file():
        data["obligations"] = _read_yaml(obligations_file).get("obligations") or []
    return Pack.model_validate(data)


def _read_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data
