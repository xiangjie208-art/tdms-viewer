from __future__ import annotations

from copy import deepcopy
from hashlib import sha1
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QStandardPaths

DEFAULT_SESSION = {
    "version": 1,
    "data_folder": "",
    "blank_folder": "",
    "file_marks": {},
    "file_notes": {},
    "regions": [],
    "view_ranges": {},
}


def app_data_dir() -> Path:
    configured = os.environ.get("TDMS_VIEWER_DATA_DIR")
    if configured:
        root = Path(configured)
    elif getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent / "user_data"
    else:
        root = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    root.mkdir(parents=True, exist_ok=True)
    return root


def session_path(data_folder: str) -> Path:
    resolved = Path(data_folder).resolve()
    portable_identity = "/".join(resolved.parts[1:]).lower()
    digest = sha1(portable_identity.encode("utf-8")).hexdigest()[:16]
    folder = app_data_dir() / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{digest}.json"


def load_session(data_folder: str):
    state = deepcopy(DEFAULT_SESSION)
    path = session_path(data_folder)
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass
    state["data_folder"] = str(Path(data_folder).resolve())
    return state


def save_session(state: dict):
    data_folder = state.get("data_folder")
    if not data_folder:
        return
    path = session_path(data_folder)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def snapshots_dir(data_folder: str) -> Path:
    resolved = Path(data_folder).resolve()
    portable_identity = "/".join(resolved.parts[1:]).lower()
    digest = sha1(portable_identity.encode("utf-8")).hexdigest()[:16]
    folder = app_data_dir() / "snapshots" / digest
    folder.mkdir(parents=True, exist_ok=True)
    return folder
