from pathlib import Path

from tdms_fingerprint_viewer.session import app_data_dir, load_session, save_session, session_path


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
