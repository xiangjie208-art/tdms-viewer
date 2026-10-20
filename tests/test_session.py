from pathlib import Path

import json

from tdms_fingerprint_viewer.session import (
    SESSION_VERSION, app_data_dir, load_session, load_session_file,
    save_session, save_session_file, session_path,
    normalize_session,
)


def test_session_round_trip_uses_configured_private_directory(tmp_path: Path, monkeypatch):
    state_root = tmp_path / "private_state"
    data_folder = tmp_path / "experiment"
    data_folder.mkdir()
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(state_root))

    state = load_session(str(data_folder))
    state["file_marks"]["test_1.tdms"] = "候选"
    save_session(state)

    assert app_data_dir() == state_root
    assert session_path(str(data_folder)).is_file()
    assert load_session(str(data_folder))["file_marks"]["test_1.tdms"] == "候选"


def test_legacy_session_migrates_absolute_file_keys_to_relative_names(tmp_path: Path, monkeypatch):
    state_root = tmp_path / "state"
    data_folder = tmp_path / "experiment"
    data_folder.mkdir()
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(state_root))
    source = data_folder / "sample_1.tdms"
    legacy = {
        "version": 1,
        "data_folder": str(data_folder),
        "file_marks": {str(source): "候选"},
        "file_notes": {str(source): "旧备注"},
        "view_ranges": {str(source): [1.0, 2.0]},
        "regions": [{"id": "old", "file": str(source), "start_s": 1.0, "end_s": 2.0}],
    }
    session_path(str(data_folder)).write_text(json.dumps(legacy), encoding="utf-8")

    restored = load_session(str(data_folder))

    assert restored["version"] == SESSION_VERSION
    assert restored["file_marks"] == {"sample_1.tdms": "候选"}
    assert restored["file_notes"] == {"sample_1.tdms": "旧备注"}
    assert restored["view_ranges"] == {"sample_1.tdms": [1.0, 2.0]}
    assert restored["regions"][0]["file"] == "sample_1.tdms"


def test_corrupt_session_recovers_previous_atomic_backup(tmp_path: Path, monkeypatch):
    data_folder = tmp_path / "experiment"
    data_folder.mkdir()
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "state"))
    state = load_session(str(data_folder))
    state["file_marks"]["sample.tdms"] = "候选"
    save_session(state)
    state["file_marks"]["sample.tdms"] = "排除"
    save_session(state)
    session_path(str(data_folder)).write_text("{broken", encoding="utf-8")

    restored = load_session(str(data_folder))

    assert restored["file_marks"]["sample.tdms"] == "候选"
    assert restored["_recovered_from_backup"] is True


def test_named_session_file_round_trip_preserves_processing_state(tmp_path: Path):
    data_folder = tmp_path / "experiment"
    data_folder.mkdir()
    path = tmp_path / "screening.tdms-session.json"
    state = {
        "data_folder": str(data_folder),
        "session_name": "screening",
        "file_validity": {"sample_8.tdms": "有效", "sample_9.tdms": "无效"},
        "processing": {"current_file": "sample_8.tdms", "current_channel": "Current/ai0"},
    }

    save_session_file(state, path)
    restored = load_session_file(path)

    assert restored["session_name"] == "screening"
    assert restored["processing"]["current_file"] == "sample_8.tdms"
    assert restored["processing"]["current_channel"] == "Current/ai0"
    assert restored["file_validity"] == {"sample_8.tdms": "有效", "sample_9.tdms": "无效"}


def test_session_normalizes_file_validity_and_defaults_legacy_files_to_unreviewed(tmp_path):
    source = tmp_path / "sample.tdms"
    legacy = normalize_session({"file_marks": {source.name: "候选"}}, tmp_path)
    assert legacy["file_validity"] == {}
    state = normalize_session({"file_validity": {
        str(source): "有效", "invalid.tdms": "无效", "unknown.tdms": "unexpected",
    }}, tmp_path)
    assert state["file_validity"] == {source.name: "有效", "invalid.tdms": "无效"}
