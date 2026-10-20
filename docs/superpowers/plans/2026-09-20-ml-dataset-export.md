# Machine Learning Dataset Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click workflow that converts manually saved regions from multiple molecule folders into a minimal, traceable machine-learning dataset containing one feature table and one compressed raw-waveform file per valid sample.

**Architecture:** Move the existing pA conversion into a shared unit module, then place source discovery, feature extraction, validation, deduplication, and atomic output in a Qt-independent dataset module. A focused dialog maps folders to editable labels and runs the pure builder through a cancellable `QRunnable`; the existing screening page only owns the entry button.

**Tech Stack:** Python 3.10–3.13, NumPy, nptdms, PySide6, pytest, Ruff

**Spec:** `docs/superpowers/specs/2026-09-20-ml-dataset-export-design.md`

## Global Constraints

- Scan only first-level subfolders of the selected root and read each folder's default automatic session with `load_session(folder)`.
- Export the complete dataset without train, validation, or test splits.
- Create only `dataset.csv` and `waveforms/*.npz` inside each final dataset directory.
- Save NPZ arrays as unfiltered `float64` `time_s` and `current_pa`; compute features from baseline-corrected pA values.
- Use one editable label per source folder; allow several source folders to share the same label.
- Default the shared peak threshold to exactly `10 pA` and use a wheel-safe numeric control.
- Treat `end_index` as exclusive and preserve exact `[start_index:end_index]` reconstruction.
- Continue after sample-local failures, keep CSV rows and NPZ files one-to-one, and report skips only in the completion dialog.
- Build in a temporary sibling directory and publish the final directory only after successful CSV completion; cancellation or a dataset-wide failure removes temporary output.
- Keep all feature values finite and set undefined zero-peak, one-peak, constant-signal, and insufficient-spectrum statistics to `0`.
- Do not add new runtime dependencies.

## Review Focus

- A stale session that requests a channel no longer present must skip the region instead of silently using the longest channel; Task 2 pins the exact channel-match check.
- A record with negative, reversed, empty, or out-of-range indices must be skipped instead of clamped into a different sample; Task 2 covers strict bound validation.
- Duplicate regions that resolve through different relative-path spellings must produce one sample; Task 2 deduplicates after resolving the source path and normalized channel/bounds.
- A waveform write failure must leave neither a CSV row nor a partial NPZ; Task 2 injects a write failure and checks cleanup.
- Cancellation after some samples have been processed must remove the temporary tree and publish no final directory; Task 2 exercises cancellation between regions and Task 3 verifies the stop control reaches the worker.

---

### Task 1: Shared unit conversion and deterministic feature extraction

**Files:**
- Create: `src/tdms_fingerprint_viewer/units.py`
- Create: `src/tdms_fingerprint_viewer/dataset_export.py`
- Modify: `src/tdms_fingerprint_viewer/cluster_panel.py:10-25,240-248`
- Create: `tests/test_dataset_export.py`
- Modify: `tests/test_clustering.py`

**Interfaces:**
- Produces: `current_factor(unit: str) -> float | None` in `units.py`.
- Produces: `FEATURE_VERSION: str`, `SOURCE_COLUMNS: tuple[str, ...]`, `FEATURE_COLUMNS: tuple[str, ...]`, and `DATASET_COLUMNS: tuple[str, ...]` in `dataset_export.py`.
- Produces: `extract_sample_features(amplitude_pa: np.ndarray, dt: float, threshold_pa: float = 10.0) -> dict[str, int | float]`.
- Preserves: `ClusterPanel` converts all currently supported units exactly as before.

- [ ] **Step 1: Write failing unit-conversion tests**

Add these cases to `tests/test_dataset_export.py`:

```python
import numpy as np
import pytest

from tdms_fingerprint_viewer.units import current_factor


@pytest.mark.parametrize(
    ("unit", "factor"),
    [("A", 1e12), ("mA", 1e9), ("uA", 1e6), ("µA", 1e6),
     ("μA", 1e6), ("nA", 1e3), ("pA", 1.0), (" V ", 1000.0),
     ("volt", 1000.0), ("VOLTS", 1000.0)],
)
def test_current_factor_converts_supported_units(unit, factor):
    assert current_factor(unit) == factor


def test_current_factor_rejects_unknown_units():
    assert current_factor("a.u.") is None
```

- [ ] **Step 2: Run the unit tests and observe the missing module failure**

Run: `pytest tests/test_dataset_export.py -v`

Expected: collection fails because `tdms_fingerprint_viewer.units` does not exist.

- [ ] **Step 3: Create the shared unit module and update automatic clustering**

Create `src/tdms_fingerprint_viewer/units.py` with the existing calibration:

```python
CURRENT_TO_PA = {
    "A": 1e12, "mA": 1e9, "uA": 1e6, "µA": 1e6,
    "μA": 1e6, "nA": 1e3, "pA": 1.0,
}
VOLTAGE_TO_PA = 1000.0
VOLTAGE_UNITS = {"v", "volt", "volts"}


def current_factor(unit: str) -> float | None:
    text = str(unit).strip()
    if text.casefold() in VOLTAGE_UNITS:
        return VOLTAGE_TO_PA
    return CURRENT_TO_PA.get(text)
```

Delete the duplicate constants and function from `cluster_panel.py`, import all four shared names there, and retain its current unit handling. Extend the existing clustering unit test to include both microampere symbols so the refactor cannot narrow support.

- [ ] **Step 4: Run conversion and clustering tests**

Run: `pytest tests/test_dataset_export.py tests/test_clustering.py -v`

Expected: all conversion and existing clustering tests pass.

- [ ] **Step 5: Write failing feature-extraction tests**

Append tests that use simple signals with analytically visible peaks and a sampled sinusoid:

```python
from tdms_fingerprint_viewer.dataset_export import (
    DATASET_COLUMNS, FEATURE_VERSION, extract_sample_features,
)


def test_feature_column_contract_is_stable():
    assert FEATURE_VERSION == "1"
    assert DATASET_COLUMNS[0:4] == ("sample_id", "label", "source_folder", "source_file")
    assert DATASET_COLUMNS[-4:] == (
        "bandpower_0_100", "bandpower_100_250",
        "bandpower_250_500", "bandpower_500_1000",
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
    assert result["interpeak_interval_mean_ms"] == pytest.approx(4.0)
    assert result["peak_rate_hz"] == pytest.approx(250.0)


def test_extract_sample_features_finds_sine_frequency_and_bandpower():
    dt = 1 / 4000
    time = np.arange(4000) * dt
    result = extract_sample_features(5 * np.sin(2 * np.pi * 200 * time), dt)
    assert result["dominant_frequency_hz"] == pytest.approx(200.0, abs=1.0)
    assert result["bandpower_100_250"] > 0.99
    assert sum(result[name] for name in DATASET_COLUMNS if name.startswith("bandpower_")) == pytest.approx(1.0)


@pytest.mark.parametrize("amplitude", [np.zeros(8), np.array([12.0]), np.array([0.0, 11.0, 0.0])])
def test_extract_sample_features_returns_only_finite_values(amplitude):
    result = extract_sample_features(amplitude, dt=0.001)
    assert all(np.isfinite(float(value)) for value in result.values())
```

- [ ] **Step 6: Run the focused feature tests and observe the missing API failure**

Run: `pytest tests/test_dataset_export.py -v`

Expected: import fails because `dataset_export.py` and its public names do not exist.

- [ ] **Step 7: Implement constants and `extract_sample_features`**

Create `dataset_export.py`. Define all 45 columns exactly in spec order. Implement the function with these concrete operations:

```python
def extract_sample_features(amplitude_pa, dt, threshold_pa=10.0):
    values = np.asarray(amplitude_pa, dtype=np.float64)
    if values.ndim != 1 or not len(values):
        raise ValueError("片段没有采样值")
    if not np.isfinite(values).all() or not np.isfinite(dt) or dt <= 0:
        raise ValueError("片段包含无效采样值或采样间隔")
    if not np.isfinite(threshold_pa) or threshold_pa < 0:
        raise ValueError("峰幅值阈值必须为非负有限值")

    above = values > threshold_pa
    transitions = np.diff(np.r_[False, above, False].astype(np.int8))
    starts = np.flatnonzero(transitions == 1)
    ends = np.flatnonzero(transitions == -1)
    peak_positions = np.array(
        [start + int(np.argmax(values[start:end])) for start, end in zip(starts, ends)],
        dtype=int,
    )
```

Use `np.trapezoid` when available and `np.trapz` as the NumPy compatibility fallback. Compute duration from `(len(values) - 1) * dt`, peak rate from `len(starts) / (len(values) * dt)`, and peak widths from `(ends - starts) * dt`. For the FFT, subtract the segment mean, multiply by `np.hanning`, compute `np.fft.rfft`, restrict to `0 < f <= min(1000, Nyquist)`, and return zeros when normalized power is unavailable. Use the four half-open bands from the spec, with 1000 Hz included in the last band.

- [ ] **Step 8: Run focused tests and the full clustering regression**

Run: `pytest tests/test_dataset_export.py tests/test_clustering.py tests/test_batch_clustering.py -v`

Expected: all pass.

- [ ] **Step 9: Commit Task 1**

```powershell
git add src/tdms_fingerprint_viewer/units.py src/tdms_fingerprint_viewer/dataset_export.py src/tdms_fingerprint_viewer/cluster_panel.py tests/test_dataset_export.py tests/test_clustering.py
git commit -m "feat: add dataset feature extraction"
```

---

### Task 2: Discover saved regions and build an atomic dataset

**Files:**
- Modify: `src/tdms_fingerprint_viewer/dataset_export.py`
- Modify: `tests/test_dataset_export.py`

**Interfaces:**
- Consumes: `current_factor`, `DATASET_COLUMNS`, `extract_sample_features`, `discover_tdms`, `load_trace`, `load_session`, `resolve_region_file`, and package `__version__`.
- Produces: immutable `DatasetSource`, `SkippedSample`, and `DatasetBuildSummary` dataclasses.
- Produces: `discover_dataset_sources(root: Path) -> list[DatasetSource]`.
- Produces: `build_ml_dataset(root: Path, output_parent: Path, selected_sources: Sequence[DatasetSource], threshold_pa: float, progress: Callable[[int, int, str], None] | None = None, cancelled: Callable[[], bool] | None = None) -> DatasetBuildSummary`.

- [ ] **Step 1: Write failing source-discovery tests**

Use a temporary application-data directory so tests exercise the real default-session mapping:

```python
from dataclasses import replace
from pathlib import Path

from tdms_fingerprint_viewer.dataset_export import discover_dataset_sources
from tdms_fingerprint_viewer.session import save_session


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
```

- [ ] **Step 2: Run the discovery test and observe the missing function failure**

Run: `pytest tests/test_dataset_export.py::test_discover_dataset_sources_reads_first_level_default_sessions -v`

Expected: import or attribute failure for `discover_dataset_sources`.

- [ ] **Step 3: Implement `DatasetSource` and first-level discovery**

Add the immutable source model and sort folders by case-folded name plus original name:

```python
@dataclass(frozen=True)
class DatasetSource:
    folder: Path
    folder_name: str
    label: str
    tdms_count: int
    region_count: int
    included: bool


def discover_dataset_sources(root: Path) -> list[DatasetSource]:
    root = Path(root)
    if not root.is_dir():
        raise ValueError("总目录不存在")
    result = []
    folders = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: (path.name.casefold(), path.name))
    for folder in folders:
        region_count = len(load_session(str(folder)).get("regions", []))
        result.append(DatasetSource(
            folder=folder.resolve(), folder_name=folder.name, label=folder.name,
            tdms_count=len(discover_tdms(folder)), region_count=region_count,
            included=region_count > 0,
        ))
    return result
```

- [ ] **Step 4: Run discovery tests**

Run: `pytest tests/test_dataset_export.py -v`

Expected: discovery and Task 1 tests pass.

- [ ] **Step 5: Write failing end-to-end build tests**

Create a helper that writes a real session and monkeypatches only TDMS loading:

```python
from tdms_fingerprint_viewer.core import ChannelInfo
from tdms_fingerprint_viewer.dataset_export import build_ml_dataset


def make_source(tmp_path, monkeypatch, regions):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "app-data"))
    root = tmp_path / "molecules"
    folder = root / "glycine"
    folder.mkdir(parents=True)
    (folder / "trace_1.tdms").touch()
    save_session({"data_folder": str(folder), "regions": regions})
    return root, folder, discover_dataset_sources(root)[0]


def fake_trace(values=None, key="Signal/Current", unit="pA", dt=0.001):
    data = np.asarray(values if values is not None else [1, 2, 20, 22, 2, 1], dtype=float)
    channel = ChannelInfo("Signal", "Current", len(data), dt, unit)
    return data, channel, [channel]


def test_build_ml_dataset_writes_minimal_traceable_output(tmp_path, monkeypatch):
    regions = [{
        "file": "trace_1.tdms", "file_name": "trace_1.tdms",
        "channel": "Signal/Current", "start_index": 1,
        "end_index_exclusive": 5, "cluster_detection": {"manually_reviewed": True},
    }]
    root, folder, source = make_source(tmp_path, monkeypatch, regions)
    monkeypatch.setattr("tdms_fingerprint_viewer.dataset_export.load_trace", lambda path, key: fake_trace())

    summary = build_ml_dataset(root, tmp_path / "exports", [replace(source, label="Gly")], 10.0)

    assert summary.sample_count == 1
    assert summary.skipped == ()
    assert sorted(path.relative_to(summary.output_dir).as_posix() for path in summary.output_dir.rglob("*")) == [
        "dataset.csv", "waveforms", "waveforms/sample_000001.npz",
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
```

Add focused tests for the Review Focus cases:

```python
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
    root, folder, source = make_source(tmp_path, monkeypatch, regions)
    monkeypatch.setattr("tdms_fingerprint_viewer.dataset_export.load_trace", lambda path, key: fake_trace())

    summary = build_ml_dataset(root, tmp_path / "exports", [source], 10.0)

    assert summary.sample_count == 1
    assert len(summary.skipped) == 5
    assert any("原通道" in skipped.reason for skipped in summary.skipped)
    assert sum("索引" in skipped.reason for skipped in summary.skipped) == 4


def test_build_deduplicates_resolved_source_channel_and_bounds(tmp_path, monkeypatch):
    base = {
        "file_name": "trace_1.tdms", "channel": "Signal/Current",
        "start_index": 1, "end_index_exclusive": 5,
    }
    root, folder, source = make_source(
        tmp_path, monkeypatch, [{**base, "file": "trace_1.tdms"}, {**base, "file": "./trace_1.tdms"}],
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
    root, folder, source = make_source(tmp_path, monkeypatch, regions)
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
    root, folder, source = make_source(tmp_path, monkeypatch, regions)
    monkeypatch.setattr("tdms_fingerprint_viewer.dataset_export.load_trace", lambda path, key: fake_trace())
    output_parent = tmp_path / "exports"
    progress_calls = []

    summary = build_ml_dataset(
        root, output_parent, [source], 10.0,
        progress=lambda done, total, text: progress_calls.append((done, total, text)),
        cancelled=lambda: bool(progress_calls),
    )

    assert summary.cancelled is True
    assert summary.output_dir is None
    assert list(output_parent.iterdir()) == []


def test_build_with_no_valid_sample_publishes_no_dataset(tmp_path, monkeypatch):
    regions = [{
        "file": "trace_1.tdms", "file_name": "trace_1.tdms",
        "channel": "Signal/Current", "start_index": 0, "end_index_exclusive": 2,
    }]
    root, folder, source = make_source(tmp_path, monkeypatch, regions)
    monkeypatch.setattr(
        "tdms_fingerprint_viewer.dataset_export.load_trace",
        lambda path, key: fake_trace(unit="a.u."),
    )
    output_parent = tmp_path / "exports"

    with pytest.raises(ValueError, match="没有可导出的有效样本"):
        build_ml_dataset(root, output_parent, [source], 10.0)

    assert list(output_parent.iterdir()) == []
```

- [ ] **Step 6: Run the build tests and observe the missing builder failure**

Run: `pytest tests/test_dataset_export.py -v`

Expected: build tests fail because the dataclasses and builder are absent.

- [ ] **Step 7: Implement source validation, caching, deduplication, and output assembly**

Add these result models:

```python
@dataclass(frozen=True)
class SkippedSample:
    source: str
    reason: str


@dataclass(frozen=True)
class DatasetBuildSummary:
    output_dir: Path | None
    sample_count: int
    skipped: tuple[SkippedSample, ...]
    cancelled: bool = False
```

Implement helpers with strict semantics:

```python
def _strict_region_bounds(region: dict, dt: float, length: int) -> tuple[int, int]:
    if "start_index" in region and "end_index_exclusive" in region:
        start = int(region["start_index"])
        end = int(region["end_index_exclusive"])
    else:
        start = int(round(float(region["start_s"]) / dt))
        end = int(round(float(region["end_s"]) / dt)) + 1
    if start < 0 or end <= start or end > length:
        raise ValueError("片段索引超出原始通道范围")
    return start, end
```

The builder must:

1. Validate root, output parent, nonempty selected sources, nonempty labels, and finite nonnegative threshold.
2. Create `.<final-name>.tmp-<uuid>` beside the future final directory and its `waveforms` child.
3. Reload each selected folder session, sort regions by resolved file/channel/bounds, and resolve files with `resolve_region_file`.
4. Cache `(resolved_path, requested_channel)` loads. Reject `selected.key != requested_channel`; never accept `load_trace` fallback for a stale requested channel.
5. Convert the full channel once, compute its finite-value median baseline, and reject a region containing any nonfinite sample.
6. Normalize the resolved path before constructing the deduplication key `(folder.resolve(), file.resolve(), channel.key, start, end)`.
7. Compute the feature dictionary, write NPZ to a temporary sample filename, replace it into its final NPZ name, then append the CSV row in memory.
8. Write `dataset.csv` with `csv.DictWriter(..., encoding="utf-8-sig")` only after region processing; raise `ValueError("没有可导出的有效样本")` when there are no valid rows.
9. Rename the complete temporary tree to the unused timestamped final name.
10. On cancellation, delete the temporary tree and return `cancelled=True`; on a dataset-wide exception, delete it and re-raise.

Keep per-sample exceptions within the region loop and convert them to `SkippedSample`. Keep directory creation, final CSV writing, and final rename outside that handler so dataset-wide failures remain visible.

- [ ] **Step 8: Run the end-to-end and failure-path tests**

Run: `pytest tests/test_dataset_export.py -v`

Expected: all feature, discovery, build, deduplication, cleanup, and cancellation tests pass.

- [ ] **Step 9: Run related session and exporting regressions**

Run: `pytest tests/test_session.py tests/test_exporting.py tests/test_dataset_export.py -v`

Expected: all pass.

- [ ] **Step 10: Commit Task 2**

```powershell
git add src/tdms_fingerprint_viewer/dataset_export.py tests/test_dataset_export.py
git commit -m "feat: build machine learning datasets"
```

---

### Task 3: Dataset dialog, editable label mapping, background progress, and cancellation

**Files:**
- Create: `src/tdms_fingerprint_viewer/dataset_dialog.py`
- Create: `tests/test_dataset_dialog.py`

**Interfaces:**
- Consumes: `DatasetSource`, `DatasetBuildSummary`, `discover_dataset_sources`, `build_ml_dataset`, and `WheelSafeDoubleSpinBox`.
- Produces: `DatasetBuildSignals(QObject)` with `progress(int, int, str)`, `finished(object)`, and `failed(str)` signals.
- Produces: `DatasetBuildWorker(QRunnable)` with `cancel()` and a thread-safe `Event`.
- Produces: `DatasetDialog(QDialog)` with `selected_sources() -> list[DatasetSource]`, `refresh_build_enabled()`, `start_build()`, `stop_build()`, and completion handlers.

- [ ] **Step 1: Write failing dialog construction and validation tests**

Create `tests/test_dataset_dialog.py` using the project's direct `QApplication` pattern:

```python
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tdms_fingerprint_viewer.dataset_dialog import DatasetDialog
from tdms_fingerprint_viewer.dataset_export import DatasetSource
from tdms_fingerprint_viewer.widgets import WheelSafeDoubleSpinBox


def app():
    return QApplication.instance() or QApplication([])


def sources(tmp_path):
    return [
        DatasetSource(tmp_path / "A", "A", "A", 2, 3, True),
        DatasetSource(tmp_path / "B", "B", "B", 1, 0, False),
    ]


def test_dataset_dialog_defaults_and_editable_label_mapping(tmp_path):
    app()
    dialog = DatasetDialog(discoverer=lambda root: sources(tmp_path))
    dialog.set_root(tmp_path)
    assert isinstance(dialog.threshold_spin, WheelSafeDoubleSpinBox)
    assert dialog.threshold_spin.value() == 10.0
    assert dialog.source_table.rowCount() == 2
    assert dialog.source_table.item(0, 0).checkState() == Qt.Checked
    assert dialog.source_table.item(1, 0).checkState() == Qt.Unchecked
    dialog.source_table.item(0, 2).setText("same-molecule")
    selected = dialog.selected_sources()
    assert len(selected) == 1
    assert selected[0].label == "same-molecule"


def test_dataset_dialog_enables_build_only_with_valid_inputs(tmp_path):
    app()
    dialog = DatasetDialog(discoverer=lambda root: sources(tmp_path))
    dialog.set_root(tmp_path)
    assert not dialog.build_button.isEnabled()
    dialog.set_output_parent(tmp_path / "exports")
    assert dialog.build_button.isEnabled()
    dialog.source_table.item(0, 2).setText("")
    assert not dialog.build_button.isEnabled()
```

- [ ] **Step 2: Run dialog tests and observe the missing module failure**

Run: `pytest tests/test_dataset_dialog.py -v`

Expected: collection fails because `dataset_dialog.py` does not exist.

- [ ] **Step 3: Implement the dialog structure and validation**

Create the dialog with dependency injection for deterministic tests:

```python
class DatasetDialog(QDialog):
    def __init__(self, parent=None, *, discoverer=discover_dataset_sources, builder=build_ml_dataset):
        super().__init__(parent)
        self.discoverer = discoverer
        self.builder = builder
        self.sources = []
        self.worker = None
        self.setWindowTitle("制作机器学习数据集")
        self.resize(900, 620)
```

Build the directory selectors, five-column table, threshold spin box, progress bar, status label, and buttons. Store each `DatasetSource` in the first-column item's `Qt.UserRole`; when returning selected sources, use `dataclasses.replace(source, label=edited_text.strip(), included=True)`. Connect check-state and label changes to `refresh_build_enabled()`. The build button requires a valid root, output parent, at least one checked source with `region_count > 0`, and nonempty labels.

- [ ] **Step 4: Run dialog validation tests**

Run: `pytest tests/test_dataset_dialog.py -v`

Expected: construction, default threshold, default inclusion, label editing, and button validation pass.

- [ ] **Step 5: Write failing worker-state and cancellation tests**

Add a synchronous worker test and a dialog state test:

```python
from PySide6.QtTest import QSignalSpy

from tdms_fingerprint_viewer.dataset_dialog import DatasetBuildWorker
from tdms_fingerprint_viewer.dataset_export import DatasetBuildSummary


def test_dataset_worker_forwards_progress_and_cancellation(tmp_path):
    app()
    calls = {}

    def builder(root, output, selected, threshold, progress, cancelled):
        progress(1, 2, "A / trace_1.tdms")
        calls["cancelled"] = cancelled()
        return DatasetBuildSummary(tmp_path / "done", 1, (), calls["cancelled"])

    worker = DatasetBuildWorker(tmp_path, tmp_path, sources(tmp_path)[:1], 10.0, builder)
    progress_spy = QSignalSpy(worker.signals.progress)
    finish_spy = QSignalSpy(worker.signals.finished)
    worker.cancel()
    worker.run()
    assert calls["cancelled"] is True
    assert progress_spy.count() == 1
    assert finish_spy.count() == 1


def test_dialog_stop_requests_worker_cancellation(tmp_path):
    app()
    dialog = DatasetDialog(discoverer=lambda root: sources(tmp_path))
    dialog.set_root(tmp_path)
    dialog.set_output_parent(tmp_path / "exports")
    class StubWorker:
        def __init__(self): self.was_cancelled = False
        def cancel(self): self.was_cancelled = True
    dialog.worker = StubWorker()
    dialog.set_running(True)
    dialog.stop_build()
    assert dialog.worker.was_cancelled
    assert "正在停止" in dialog.status_label.text()
```

- [ ] **Step 6: Run worker tests and observe missing behavior**

Run: `pytest tests/test_dataset_dialog.py -v`

Expected: worker tests fail until signals, cancellation, and running-state methods exist.

- [ ] **Step 7: Implement the worker and completion summaries**

Use `threading.Event` inside `DatasetBuildWorker`. Its `run()` passes `self.signals.progress.emit` and `self.cancelled.is_set` into the builder. It emits `finished(summary)` for normal and cancelled summaries and `failed(str(exc))` for unhandled failures.

`DatasetDialog.start_build()` captures immutable selected-source values, creates the worker, connects its signals, calls `set_running(True)`, and submits it to `QThreadPool.globalInstance()`. Progress updates the bar range/value and current source text. `stop_build()` calls `worker.cancel()` once and changes the status to “正在停止，等待当前操作完成…”.

On success, show output directory, valid sample count, skipped count, and all skip source/reason lines in a selectable details box or message dialog. On cancellation, report that no dataset was created. On failure, show the error and restore controls. Keep the dialog open after all outcomes so the user can inspect the summary.

- [ ] **Step 8: Run all dialog tests**

Run: `pytest tests/test_dataset_dialog.py -v`

Expected: all pass without opening a blocking file picker or message box.

- [ ] **Step 9: Commit Task 3**

```powershell
git add src/tdms_fingerprint_viewer/dataset_dialog.py tests/test_dataset_dialog.py
git commit -m "feat: add dataset export dialog"
```

---

### Task 4: Main-window entry, product documentation, and full verification

**Files:**
- Modify: `src/tdms_fingerprint_viewer/main_window.py:15-30,550-590`
- Modify: `src/tdms_fingerprint_viewer/__init__.py`
- Modify: `tests/test_gui_smoke.py`
- Modify: `README.md`
- Modify: `README_EN.md`
- Modify: `docs/USER_GUIDE.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `DatasetDialog`.
- Produces: `MainWindow.open_dataset_dialog()` and `MainWindow.dataset_button` on the screening page.
- Updates: package version from `2.11.0` to `2.12.0` and documents the user-facing workflow in both README languages.

- [ ] **Step 1: Write a failing main-window entry test**

Add to `tests/test_gui_smoke.py`:

```python
def test_screening_page_opens_machine_learning_dataset_dialog(monkeypatch):
    app = QApplication.instance() or QApplication([])
    opened = []

    class StubDialog:
        def __init__(self, parent):
            assert isinstance(parent, MainWindow)
        def exec(self):
            opened.append(True)

    monkeypatch.setattr("tdms_fingerprint_viewer.main_window.DatasetDialog", StubDialog)
    window = MainWindow()
    assert window.dataset_button.text() == "制作机器学习数据集…"
    window.dataset_button.click()
    assert opened == [True]
    window.close()
```

- [ ] **Step 2: Run the entry test and observe the missing button failure**

Run: `pytest tests/test_gui_smoke.py::test_screening_page_opens_machine_learning_dataset_dialog -v`

Expected: failure because `DatasetDialog` and `dataset_button` are not connected to `MainWindow`.

- [ ] **Step 3: Add the screening-page entry**

Import `DatasetDialog`, add the independent button below the existing saved-region action row, and implement:

```python
def open_dataset_dialog(self):
    dialog = DatasetDialog(self)
    dialog.exec()
```

The button remains enabled even when no data folder is currently open because the dialog selects its own total directory.

- [ ] **Step 4: Run the GUI entry and dialog tests**

Run: `pytest tests/test_gui_smoke.py tests/test_dataset_dialog.py -v`

Expected: all pass.

- [ ] **Step 5: Update user-facing documentation and version metadata**

Make these exact documentation changes:

- Add one-click dataset creation to the “频谱、记录与导出” feature list in `README.md` and “Spectrum, Records, and Export” in `README_EN.md`.
- Add a workflow step after region saving that selects the parent molecule directory, edits/merges labels, keeps the default `10 pA` feature threshold, and starts the build.
- Add a “制作机器学习数据集” section to `docs/USER_GUIDE.md` showing the two-file output tree, first-level folder labeling rule, editable label merge, raw pA NPZ arrays, feature categories, skip summary, and complete-dataset scope.
- Add a `2.12.0` changelog entry dated `2026-09-20` describing label mapping, minimal output, pA normalization, baseline/peak/spectrum features, background progress, cancellation, and local-failure continuation.
- Change `src/tdms_fingerprint_viewer/__init__.py` to `__version__ = "2.12.0"`.

- [ ] **Step 6: Run the focused product tests**

Run: `pytest tests/test_dataset_export.py tests/test_dataset_dialog.py tests/test_gui_smoke.py tests/test_clustering.py tests/test_batch_clustering.py -v`

Expected: all pass.

- [ ] **Step 7: Run the complete regression suite**

Run: `pytest`

Expected: all tests pass; the baseline 83 tests plus the new dataset tests report no failures.

- [ ] **Step 8: Run static and patch checks**

Run: `ruff check .`

Expected: no Ruff errors.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 9: Inspect the final diff against the specification**

Run: `git diff --stat bc909a2..HEAD` and `git status --short`.

Confirm from the diff that:

- the final output has no image, HTML, JSON, split, or standalone error-report option;
- all 45 CSV columns are present in the specified order;
- every CSV row is appended only after its NPZ exists;
- cancellation and dataset-wide errors delete the temporary directory;
- existing automatic clustering still uses the same unit conversion;
- the UI does not require a currently open data folder.

- [ ] **Step 10: Commit Task 4**

```powershell
git add src/tdms_fingerprint_viewer/main_window.py src/tdms_fingerprint_viewer/__init__.py tests/test_gui_smoke.py README.md README_EN.md docs/USER_GUIDE.md CHANGELOG.md
git commit -m "feat: integrate machine learning dataset export"
```

- [ ] **Step 11: Verify the committed branch is clean**

Run: `pytest; ruff check .; git diff --check; git status --short --branch`

Expected: tests and Ruff pass, `git diff --check` prints nothing, and status shows `codex/ml-dataset-export` with no uncommitted files.
