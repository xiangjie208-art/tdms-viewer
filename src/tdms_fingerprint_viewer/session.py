from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha1
import json
import os
from pathlib import Path
import shutil
import sys

from PySide6.QtCore import QStandardPaths


SESSION_VERSION = 2
DEFAULT_PROCESSING = {
    "current_file": "",
    "current_channel": "",
    "time_unit_index": 0,
    "fft_scope": "局部框选区间",
    "spectrum_mode": "FFT 幅度谱",
    "window": "Hann",
    "log_x": False,
    "log_y": False,
    "frequency_min_hz": 0.0,
    "frequency_max_hz": 1000.0,
    "blank_overlay": True,
}
DEFAULT_SESSION = {
    "version": SESSION_VERSION,
    "session_name": "",
    "data_folder": "",
    "blank_folder": "",
    "file_marks": {},
    "file_notes": {},
    "regions": [],
    "view_ranges": {},
    "processing": deepcopy(DEFAULT_PROCESSING),
    "updated_at": "",
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


def _portable_identity(data_folder: str | Path) -> str:
    resolved = Path(data_folder).resolve()
    return "/".join(resolved.parts[1:]).lower()


def session_path(data_folder: str) -> Path:
    digest = sha1(_portable_identity(data_folder).encode("utf-8")).hexdigest()[:16]
    folder = app_data_dir() / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{digest}.json"


def _relative_file_key(value, data_folder: Path) -> str:
    if not value:
        return ""
    path = Path(str(value))
    if path.is_absolute():
        try:
            return path.resolve().relative_to(data_folder.resolve()).as_posix()
        except ValueError:
            return path.name
    return path.as_posix()


def normalize_session(loaded: dict | None, data_folder: str | Path) -> dict:
    folder = Path(data_folder).resolve()
    state = deepcopy(DEFAULT_SESSION)
    if isinstance(loaded, dict):
        state.update(loaded)
    processing = deepcopy(DEFAULT_PROCESSING)
    if isinstance(state.get("processing"), dict):
        processing.update(state["processing"])
    processing["current_file"] = _relative_file_key(processing.get("current_file"), folder)
    state["processing"] = processing

    for key in ("file_marks", "file_notes", "view_ranges"):
        values = state.get(key, {})
        state[key] = {
            _relative_file_key(file_name, folder): value
            for file_name, value in values.items()
            if _relative_file_key(file_name, folder)
        } if isinstance(values, dict) else {}

    regions = []
    for original in state.get("regions", []):
        if not isinstance(original, dict):
            continue
        region = dict(original)
        file_name = region.get("file_name") or Path(region.get("file", "")).name
        region["file_name"] = file_name
        region["file"] = _relative_file_key(region.get("file") or file_name, folder)
        regions.append(region)
    state["regions"] = regions
    state["version"] = SESSION_VERSION
    state["session_name"] = str(state.get("session_name") or folder.name)
    state["data_folder"] = str(folder)
    return state


def _backup_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bak")


def _read_with_backup(path: Path) -> tuple[dict | None, bool]:
    for candidate, recovered in ((path, False), (_backup_path(path), True)):
        if not candidate.is_file():
            continue
        try:
            loaded = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(loaded, dict):
            return loaded, recovered
    return None, False


def load_session(data_folder: str):
    loaded, recovered = _read_with_backup(session_path(data_folder))
    state = normalize_session(loaded, data_folder)
    if recovered:
        state["_recovered_from_backup"] = True
    return state


def _serializable_state(state: dict) -> dict:
    result = deepcopy(state)
    for key in list(result):
        if key.startswith("_"):
            result.pop(key, None)
    return result


def _save_json(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    if path.is_file():
        shutil.copy2(path, _backup_path(path))
    temp.write_text(json.dumps(_serializable_state(state), ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def save_session(state: dict):
    data_folder = state.get("data_folder")
    if not data_folder:
        return
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _save_json(session_path(data_folder), state)


def load_session_file(path: str | Path, data_folder: str | Path | None = None) -> dict:
    source = Path(path)
    loaded, recovered = _read_with_backup(source)
    if loaded is None:
        raise ValueError(f"无法读取会话文件：{source}")
    folder_value = data_folder or loaded.get("data_folder", "")
    if not folder_value:
        raise ValueError("会话文件中没有数据文件夹信息")
    folder = Path(folder_value)
    state = normalize_session(loaded, folder)
    if recovered:
        state["_recovered_from_backup"] = True
    return state


def save_session_file(state: dict, path: str | Path) -> None:
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _save_json(Path(path), state)


def snapshots_dir(data_folder: str) -> Path:
    digest = sha1(_portable_identity(data_folder).encode("utf-8")).hexdigest()[:16]
    folder = app_data_dir() / "snapshots" / digest
    folder.mkdir(parents=True, exist_ok=True)
    return folder
