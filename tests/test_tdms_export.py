import os
from pathlib import Path
import shutil

import numpy as np
from nptdms import ChannelObject, GroupObject, RootObject, TdmsFile, TdmsWriter
import pytest

from tdms_fingerprint_viewer.tdms_export import export_tdms_files


def test_export_preserves_complete_multichannel_tdms_and_source(tmp_path):
    source = tmp_path / "测量.tdms"
    with TdmsWriter(source) as writer:
        writer.write_segment([
            RootObject(properties={"experiment": "full acquisition"}),
            GroupObject("signals", properties={"instrument": "STM"}),
            ChannelObject("signals", "current", np.arange(20.0), properties={"unit_string": "pA"}),
            ChannelObject("signals", "voltage", np.linspace(0, 1, 20)),
        ])
        writer.write_segment([
            ChannelObject("signals", "current", np.arange(20.0, 40.0)),
            ChannelObject("signals", "voltage", np.linspace(1, 2, 20)),
        ])
    source_bytes = source.read_bytes()
    os.utime(source, (1_600_000_000, 1_600_000_000))
    destination = tmp_path / "exports" / "valid"

    result = export_tdms_files([source], destination)

    exported = destination / source.name
    assert result.copied == [source.name]
    assert result.skipped == []
    assert result.errors == []
    assert exported.read_bytes() == source_bytes
    assert source.read_bytes() == source_bytes
    assert exported.stat().st_mtime == pytest.approx(source.stat().st_mtime, abs=0.01)
    saved = TdmsFile.read(exported)
    assert saved.properties["experiment"] == "full acquisition"
    assert saved["signals"].properties["instrument"] == "STM"
    assert len(saved["signals"]["current"]) == 40
    assert len(saved["signals"]["voltage"]) == 40


def test_export_skips_existing_names_and_same_directory(tmp_path):
    source = tmp_path / "trace.tdms"
    source.write_bytes(b"source data")
    destination = tmp_path / "exports"
    destination.mkdir()
    existing = destination / source.name
    existing.write_bytes(b"keep this file")

    collision = export_tdms_files([source], destination)
    same_directory = export_tdms_files([source], tmp_path)

    assert collision.skipped == same_directory.skipped == [source.name]
    assert collision.copied == same_directory.copied == []
    assert collision.errors == same_directory.errors == []
    assert existing.read_bytes() == b"keep this file"
    assert source.read_bytes() == b"source data"


@pytest.mark.parametrize("dangling", [False, True])
def test_export_skips_destination_symlinks(tmp_path, dangling):
    source = tmp_path / "trace.tdms"
    source.write_bytes(b"source data")
    destination = tmp_path / "exports"
    destination.mkdir()
    link_target = tmp_path / "link-target"
    if not dangling:
        link_target.write_bytes(b"keep link target")
    existing = destination / source.name
    try:
        existing.symlink_to(link_target)
    except OSError:
        pytest.skip("Creating symbolic links requires permission on this platform")

    result = export_tdms_files([source], destination)

    assert result.skipped == [source.name]
    assert result.copied == []
    assert result.errors == []
    assert existing.is_symlink()
    if not dangling:
        assert link_target.read_bytes() == b"keep link target"


def test_export_continues_after_missing_source_without_empty_target(tmp_path):
    missing = tmp_path / "missing.tdms"
    source = tmp_path / "trace.tdms"
    source.write_bytes(b"whole trace")
    destination = tmp_path / "exports"

    result = export_tdms_files([missing, source], destination)

    assert result.copied == [source.name]
    assert len(result.errors) == 1
    assert missing.name in result.errors[0]
    assert not (destination / missing.name).exists()
    assert (destination / source.name).read_bytes() == b"whole trace"


def test_export_exclusive_create_preserves_file_created_during_export(tmp_path, monkeypatch):
    source = tmp_path / "trace.tdms"
    source.write_bytes(b"source data")
    destination = tmp_path / "exports"
    destination.mkdir()
    target = destination / source.name
    path_open = Path.open

    def create_competing_file(path, mode="r", *args, **kwargs):
        if path == target and mode == "xb":
            with path_open(path, "wb") as writer:
                writer.write(b"keep competing export")
        return path_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", create_competing_file)

    result = export_tdms_files([source], destination)

    assert result.skipped == [source.name]
    assert result.copied == []
    assert result.errors == []
    assert target.read_bytes() == b"keep competing export"


def test_export_reports_destination_directory_failure_for_each_file(tmp_path):
    first = tmp_path / "first.tdms"
    second = tmp_path / "second.tdms"
    first.write_bytes(b"first data")
    second.write_bytes(b"second data")
    destination = tmp_path / "occupied"
    destination.write_bytes(b"existing file")

    result = export_tdms_files([first, second], destination)

    assert result.copied == result.skipped == []
    assert len(result.errors) == 2
    assert first.name in result.errors[0]
    assert second.name in result.errors[1]
    assert destination.read_bytes() == b"existing file"


def test_export_removes_its_partial_target_and_continues(tmp_path, monkeypatch):
    failing = tmp_path / "failing.tdms"
    failing.write_bytes(b"data from failing source")
    source = tmp_path / "trace.tdms"
    source.write_bytes(b"whole trace")
    destination = tmp_path / "exports"
    copyfileobj = shutil.copyfileobj

    def copy_with_failure(reader, writer, length):
        if Path(reader.name) == failing:
            writer.write(reader.read(4))
            raise OSError("simulated read failure")
        copyfileobj(reader, writer, length=length)

    monkeypatch.setattr("tdms_fingerprint_viewer.tdms_export.shutil.copyfileobj", copy_with_failure)

    result = export_tdms_files([failing, source], destination)

    assert result.copied == [source.name]
    assert len(result.errors) == 1
    assert failing.name in result.errors[0]
    assert "simulated read failure" in result.errors[0]
    assert not (destination / failing.name).exists()
    assert failing.read_bytes() == b"data from failing source"
    assert (destination / source.name).read_bytes() == b"whole trace"


def test_export_keeps_copied_data_when_attributes_cannot_be_preserved(tmp_path, monkeypatch):
    source = tmp_path / "trace.tdms"
    source.write_bytes(b"whole trace")
    destination = tmp_path / "exports"

    def fail_attributes(*args):
        raise PermissionError("attributes are read-only")

    monkeypatch.setattr("tdms_fingerprint_viewer.tdms_export.shutil.copystat", fail_attributes)

    result = export_tdms_files([source], destination)

    assert result.copied == [source.name]
    assert result.errors == []
    assert (destination / source.name).read_bytes() == b"whole trace"


def test_export_only_copies_tdms_and_reports_each_completed_file(tmp_path):
    upper_case = tmp_path / "trace.TDMS"
    upper_case.write_bytes(b"whole trace")
    ignored = tmp_path / "trace.tdms_index"
    ignored.write_bytes(b"index")
    missing = tmp_path / "missing.tdms"
    progress = []
    destination = tmp_path / "exports"

    result = export_tdms_files(
        [upper_case, ignored, missing], destination,
        progress=lambda completed, total, name: progress.append((completed, total, name)),
    )

    assert result.copied == [upper_case.name]
    assert result.skipped == [ignored.name]
    assert len(result.errors) == 1
    assert not (destination / ignored.name).exists()
    assert progress == [
        (1, 3, upper_case.name),
        (2, 3, ignored.name),
        (3, 3, missing.name),
    ]
