import csv
from dataclasses import replace
import gc
from pathlib import Path
import weakref

import numpy as np
import pytest

from tdms_fingerprint_viewer.core import ChannelInfo
from tdms_fingerprint_viewer.dataset_export import (
    DATASET_COLUMNS,
    FEATURE_VERSION,
    build_ml_dataset,
    discover_dataset_sources,
    extract_sample_features,
)
from tdms_fingerprint_viewer.session import save_session
from tdms_fingerprint_viewer.units import current_factor


@pytest.mark.parametrize(
    ("unit", "factor"),
    [
        ("A", 1e12),
        ("mA", 1e9),
        ("uA", 1e6),
        ("µA", 1e6),
        ("μA", 1e6),
        ("nA", 1e3),
        ("pA", 1.0),
        (" V ", 1000.0),
        ("volt", 1000.0),
        ("VOLTS", 1000.0),
    ],
)
def test_current_factor_converts_supported_units(unit, factor):
    assert current_factor(unit) == factor


def test_current_factor_rejects_unknown_units():
    assert current_factor("a.u.") is None


def test_feature_column_contract_is_stable():
    assert FEATURE_VERSION == "1"
    assert DATASET_COLUMNS[0:4] == ("sample_id", "label", "source_folder", "source_file")
    assert DATASET_COLUMNS[-4:] == (
        "bandpower_0_100",
        "bandpower_100_250",
        "bandpower_250_500",
        "bandpower_500_1000",
    )
    assert len(DATASET_COLUMNS) == 45


def test_extract_sample_features_measures_contiguous_threshold_peaks():
    amplitude = np.array([0, 0, 12, 20, 11, 0, 15, 0], dtype=float)

    result = extract_sample_features(amplitude, dt=0.001, threshold_pa=10.0)

    assert result["sample_count"] == 8
    assert result["duration_ms"] == pytest.approx(7.0)
    assert result["peak_count"] == 2
    assert result["peak_amplitude_mean_pa"] == pytest.approx(17.5)
    assert result["peak_amplitude_max_pa"] == pytest.approx(20.0)
    assert result["peak_width_mean_ms"] == pytest.approx(2.0)
    assert result["interpeak_interval_mean_ms"] == pytest.approx(3.0)
    assert result["peak_rate_hz"] == pytest.approx(250.0)


def test_extract_sample_features_finds_sine_frequency_and_bandpower():
    dt = 1 / 4000
    time = np.arange(4000) * dt

    result = extract_sample_features(5 * np.sin(2 * np.pi * 200 * time), dt)

    assert result["dominant_frequency_hz"] == pytest.approx(200.0, abs=1.0)
    assert result["bandpower_100_250"] > 0.99
    bandpower = sum(result[name] for name in DATASET_COLUMNS if name.startswith("bandpower_"))
    assert bandpower == pytest.approx(1.0)


@pytest.mark.parametrize(
    "amplitude",
    [np.zeros(8), np.array([12.0]), np.array([0.0, 11.0, 0.0])],
)
def test_extract_sample_features_returns_only_finite_values(amplitude):
    result = extract_sample_features(amplitude, dt=0.001)

    assert all(np.isfinite(float(value)) for value in result.values())


def test_discover_dataset_sources_reads_first_level_default_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "app-data"))
    root = tmp_path / "molecules"
    glycine = root / "甘氨酸"
    alanine = root / "丙氨酸"
    glycine.mkdir(parents=True)
    alanine.mkdir()
    (glycine / "trace_2.tdms").touch()
    (glycine / "trace_10.tdms").touch()
    save_session({"data_folder": str(glycine), "regions": [{"file": "trace_2.tdms"}]})

    sources = discover_dataset_sources(root)

    assert [source.folder_name for source in sources] == ["丙氨酸", "甘氨酸"]
    assert sources[0].tdms_count == 0
    assert sources[0].region_count == 0
    assert sources[0].included is False
    assert sources[1].label == "甘氨酸"
    assert sources[1].tdms_count == 2
    assert sources[1].region_count == 1
    assert sources[1].included is True


def make_source(tmp_path, monkeypatch, regions):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "app-data"))
    root = tmp_path / "molecules"
    folder = root / "glycine"
    folder.mkdir(parents=True)
    (folder / "trace_1.tdms").touch()
    save_session({"data_folder": str(folder), "regions": regions})
    return root, folder, discover_dataset_sources(root)[0]


def fake_trace(values=None, unit="pA", dt=0.001):
    data = np.asarray(values if values is not None else [1, 2, 20, 22, 2, 1], dtype=float)
    channel = ChannelInfo("Signal", "Current", len(data), dt, unit)
    return data, channel, [channel]


def test_build_ml_dataset_writes_minimal_traceable_output(tmp_path, monkeypatch):
    regions = [{
        "file": "trace_1.tdms",
        "file_name": "trace_1.tdms",
        "channel": "Signal/Current",
        "start_index": 1,
        "end_index_exclusive": 5,
        "cluster_detection": {"manually_reviewed": True},
    }]
    root, _folder, source = make_source(tmp_path, monkeypatch, regions)
    monkeypatch.setattr("tdms_fingerprint_viewer.dataset_export.load_trace", lambda path, key: fake_trace())

    summary = build_ml_dataset(root, tmp_path / "exports", [replace(source, label="Gly")], 10.0)

    assert summary.sample_count == 1
    assert summary.skipped == ()
    assert sorted(path.relative_to(summary.output_dir).as_posix() for path in summary.output_dir.rglob("*")) == [
        "dataset.csv",
        "waveforms",
        "waveforms/sample_000001.npz",
    ]
    saved = np.load(summary.output_dir / "waveforms/sample_000001.npz")
    np.testing.assert_allclose(saved["time_s"], [0, 0.001, 0.002, 0.003])
    np.testing.assert_allclose(saved["current_pa"], [2, 20, 22, 2])
    rows = list(csv.DictReader((summary.output_dir / "dataset.csv").open(encoding="utf-8-sig")))
    assert rows[0]["label"] == "Gly"
    assert rows[0]["selection_method"] == "cluster_review"
    assert rows[0]["start_index"] == "1"
    assert rows[0]["end_index"] == "5"
    assert rows[0]["native_unit"] == "pA"
    assert rows[0]["native_to_pa_factor"] == "1.0"
    assert rows[0]["baseline_pa"] == "2.0"
    assert rows[0]["peak_threshold_pa"] == "10.0"
    assert rows[0]["waveform_file"] == "waveforms/sample_000001.npz"
    assert saved["time_s"].dtype == np.float64
    assert saved["current_pa"].dtype == np.float64


def test_build_skips_missing_channel_and_strictly_invalid_bounds(tmp_path, monkeypatch):
    base = {"file": "trace_1.tdms", "file_name": "trace_1.tdms", "channel": "Signal/Current"}
    regions = [
        {**base, "channel": "Missing/Current", "start_index": 0, "end_index_exclusive": 2},
        {**base, "start_index": -1, "end_index_exclusive": 2},
        {**base, "start_index": 4, "end_index_exclusive": 2},
        {**base, "start_index": 2, "end_index_exclusive": 2},
        {**base, "start_index": 0, "end_index_exclusive": 99},
        {**base, "start_index": 1, "end_index_exclusive": 5},
    ]
    root, _folder, source = make_source(tmp_path, monkeypatch, regions)
    monkeypatch.setattr("tdms_fingerprint_viewer.dataset_export.load_trace", lambda path, key: fake_trace())

    summary = build_ml_dataset(root, tmp_path / "exports", [source], 10.0)

    assert summary.sample_count == 1
    assert len(summary.skipped) == 5
    assert any("原通道" in skipped.reason for skipped in summary.skipped)
    assert sum("索引" in skipped.reason for skipped in summary.skipped) == 4


def test_build_deduplicates_resolved_source_channel_and_bounds(tmp_path, monkeypatch):
    base = {
        "file_name": "trace_1.tdms",
        "channel": "Signal/Current",
        "start_index": 1,
        "end_index_exclusive": 5,
    }
    root, _folder, source = make_source(
        tmp_path,
        monkeypatch,
        [{**base, "file": "trace_1.tdms"}, {**base, "file": "./trace_1.tdms"}],
    )
    monkeypatch.setattr("tdms_fingerprint_viewer.dataset_export.load_trace", lambda path, key: fake_trace())

    summary = build_ml_dataset(root, tmp_path / "exports", [source], 10.0)

    rows = list(csv.DictReader((summary.output_dir / "dataset.csv").open(encoding="utf-8-sig")))
    assert summary.sample_count == 1
    assert len(rows) == 1
    assert len(list((summary.output_dir / "waveforms").glob("*.npz"))) == 1


def test_build_removes_partial_npz_when_one_sample_write_fails(tmp_path, monkeypatch):
    base = {"file": "trace_1.tdms", "file_name": "trace_1.tdms", "channel": "Signal/Current"}
    regions = [
        {**base, "start_index": 0, "end_index_exclusive": 2},
        {**base, "start_index": 2, "end_index_exclusive": 5},
    ]
    root, _folder, source = make_source(tmp_path, monkeypatch, regions)
    monkeypatch.setattr("tdms_fingerprint_viewer.dataset_export.load_trace", lambda path, key: fake_trace())
    real_savez = np.savez_compressed
    calls = 0

    def flaky_savez(path, **arrays):
        nonlocal calls
        calls += 1
        if calls == 1:
            Path(path).write_bytes(b"partial")
            raise OSError("disk interruption")
        return real_savez(path, **arrays)

    monkeypatch.setattr("tdms_fingerprint_viewer.dataset_export.np.savez_compressed", flaky_savez)

    summary = build_ml_dataset(root, tmp_path / "exports", [source], 10.0)

    rows = list(csv.DictReader((summary.output_dir / "dataset.csv").open(encoding="utf-8-sig")))
    assert summary.sample_count == 1
    assert len(summary.skipped) == 1
    assert [row["sample_id"] for row in rows] == ["sample_000001"]
    assert sorted(path.name for path in (summary.output_dir / "waveforms").iterdir()) == ["sample_000001.npz"]


def test_build_cancellation_removes_temporary_output(tmp_path, monkeypatch):
    base = {"file": "trace_1.tdms", "file_name": "trace_1.tdms", "channel": "Signal/Current"}
    regions = [
        {**base, "start_index": 0, "end_index_exclusive": 2},
        {**base, "start_index": 2, "end_index_exclusive": 5},
    ]
    root, _folder, source = make_source(tmp_path, monkeypatch, regions)
    monkeypatch.setattr("tdms_fingerprint_viewer.dataset_export.load_trace", lambda path, key: fake_trace())
    output_parent = tmp_path / "exports"
    progress_calls = []

    summary = build_ml_dataset(
        root,
        output_parent,
        [source],
        10.0,
        progress=lambda done, total, text: progress_calls.append((done, total, text)),
        cancelled=lambda: bool(progress_calls),
    )

    assert summary.cancelled is True
    assert summary.output_dir is None
    assert list(output_parent.iterdir()) == []


def test_build_with_no_valid_sample_publishes_no_dataset(tmp_path, monkeypatch):
    regions = [{
        "file": "trace_1.tdms",
        "file_name": "trace_1.tdms",
        "channel": "Signal/Current",
        "start_index": 0,
        "end_index_exclusive": 2,
    }]
    root, _folder, source = make_source(tmp_path, monkeypatch, regions)
    monkeypatch.setattr(
        "tdms_fingerprint_viewer.dataset_export.load_trace",
        lambda path, key: fake_trace(unit="a.u."),
    )
    output_parent = tmp_path / "exports"

    with pytest.raises(ValueError, match="没有可导出的有效样本"):
        build_ml_dataset(root, output_parent, [source], 10.0)

    assert list(output_parent.iterdir()) == []


def test_build_skips_malformed_time_bounds_without_stopping_valid_samples(tmp_path, monkeypatch):
    base = {"file": "trace_1.tdms", "file_name": "trace_1.tdms", "channel": "Signal/Current"}
    regions = [
        {**base, "start_s": "broken", "end_s": "also-broken"},
        {**base, "start_index": 1, "end_index_exclusive": 5},
    ]
    root, _folder, source = make_source(tmp_path, monkeypatch, regions)
    monkeypatch.setattr("tdms_fingerprint_viewer.dataset_export.load_trace", lambda path, key: fake_trace())

    summary = build_ml_dataset(root, tmp_path / "exports", [source], 10.0)

    assert summary.sample_count == 1
    assert len(summary.skipped) == 1
    assert "could not convert" in summary.skipped[0].reason


def test_build_releases_earlier_channel_arrays_during_large_batches(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "app-data"))
    root = tmp_path / "molecules"
    folder = root / "glycine"
    folder.mkdir(parents=True)
    regions = []
    for number in range(1, 4):
        file_name = f"trace_{number}.tdms"
        (folder / file_name).touch()
        regions.append({
            "file": file_name,
            "file_name": file_name,
            "channel": "Signal/Current",
            "start_index": 1,
            "end_index_exclusive": 5,
        })
    save_session({"data_folder": str(folder), "regions": regions})
    source = discover_dataset_sources(root)[0]
    native_marker = object()
    real_asarray = np.asarray
    converted_refs = []
    load_count = 0

    class NativeProxy:
        def __mul__(self, factor):
            converted = real_asarray([1, 2, 20, 22, 2, 1], dtype=np.float64) * factor
            converted_refs.append(weakref.ref(converted))
            return converted

    def tracking_asarray(value, dtype=None):
        if value is native_marker:
            return NativeProxy()
        return real_asarray(value, dtype=dtype)

    def tracked_load(path, key):
        nonlocal load_count
        if load_count == 2:
            gc.collect()
            assert converted_refs[0]() is None
        load_count += 1
        channel = ChannelInfo("Signal", "Current", 6, 0.001, "pA")
        return native_marker, channel, [channel]

    monkeypatch.setattr("tdms_fingerprint_viewer.dataset_export.np.asarray", tracking_asarray)
    monkeypatch.setattr("tdms_fingerprint_viewer.dataset_export.load_trace", tracked_load)

    summary = build_ml_dataset(root, tmp_path / "exports", [source], 10.0)

    assert summary.sample_count == 3
    assert load_count == 3
