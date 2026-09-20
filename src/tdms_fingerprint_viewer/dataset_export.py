"""Pure data preparation for machine-learning dataset export."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
from typing import Callable, Sequence
import uuid

import numpy as np

from . import __version__
from .core import discover_tdms, load_trace
from .exporting import resolve_region_file
from .session import load_session
from .units import current_factor


FEATURE_VERSION = "1"

SOURCE_COLUMNS = (
    "sample_id",
    "label",
    "source_folder",
    "source_file",
    "channel",
    "selection_method",
    "start_index",
    "end_index",
    "start_s",
    "end_s",
    "sampling_rate_hz",
    "native_unit",
    "native_to_pa_factor",
    "baseline_pa",
    "peak_threshold_pa",
    "waveform_file",
    "app_version",
    "feature_version",
)

FEATURE_COLUMNS = (
    "duration_ms",
    "sample_count",
    "mean_amplitude_pa",
    "median_amplitude_pa",
    "std_amplitude_pa",
    "rms_amplitude_pa",
    "max_amplitude_pa",
    "amplitude_iqr_pa",
    "positive_area_pa_ms",
    "signal_energy_pa2_ms",
    "peak_count",
    "peak_rate_hz",
    "peak_amplitude_mean_pa",
    "peak_amplitude_std_pa",
    "peak_amplitude_max_pa",
    "peak_width_mean_ms",
    "peak_width_std_ms",
    "interpeak_interval_mean_ms",
    "interpeak_interval_std_ms",
    "dominant_frequency_hz",
    "spectral_centroid_hz",
    "spectral_bandwidth_hz",
    "spectral_entropy",
    "bandpower_0_100",
    "bandpower_100_250",
    "bandpower_250_500",
    "bandpower_500_1000",
)

DATASET_COLUMNS = SOURCE_COLUMNS + FEATURE_COLUMNS


@dataclass(frozen=True)
class DatasetSource:
    folder: Path
    folder_name: str
    label: str
    tdms_count: int
    region_count: int
    included: bool


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


def discover_dataset_sources(root: Path) -> list[DatasetSource]:
    """Describe first-level molecule folders and their default sessions."""
    root = Path(root)
    if not root.is_dir():
        raise ValueError("总目录不存在")
    folders = sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: (path.name.casefold(), path.name),
    )
    result = []
    for folder in folders:
        region_count = len(load_session(str(folder)).get("regions", []))
        result.append(DatasetSource(
            folder=folder.resolve(),
            folder_name=folder.name,
            label=folder.name,
            tdms_count=len(discover_tdms(folder)),
            region_count=region_count,
            included=region_count > 0,
        ))
    return result


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


def _region_sort_key(region: dict) -> tuple:
    return (
        str(region.get("file") or region.get("file_name") or "").casefold(),
        str(region.get("channel") or "").casefold(),
        int(region.get("start_index", -1)) if str(region.get("start_index", "")).lstrip("-").isdigit() else -1,
        float(region.get("start_s", -1.0)),
        int(region.get("end_index_exclusive", -1))
        if str(region.get("end_index_exclusive", "")).lstrip("-").isdigit() else -1,
    )


def _region_source(folder_name: str, region: dict) -> str:
    file_name = region.get("file_name") or Path(str(region.get("file") or "未知文件")).name
    channel = region.get("channel") or "未知通道"
    if "start_index" in region and "end_index_exclusive" in region:
        bounds = f"{region.get('start_index')}:{region.get('end_index_exclusive')}"
    else:
        bounds = f"{region.get('start_s', '?')}–{region.get('end_s', '?')} s"
    return f"{folder_name} / {file_name} / {channel} / {bounds}"


def _unused_output_path(output_parent: Path) -> Path:
    stem = f"TDMS机器学习数据集_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    candidate = output_parent / stem
    number = 2
    while candidate.exists():
        candidate = output_parent / f"{stem}_{number}"
        number += 1
    return candidate


def build_ml_dataset(
    root: Path,
    output_parent: Path,
    selected_sources: Sequence[DatasetSource],
    threshold_pa: float,
    progress: Callable[[int, int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> DatasetBuildSummary:
    """Build a complete dataset and publish it only after all files are consistent."""
    root = Path(root).resolve()
    output_parent = Path(output_parent)
    sources = sorted(selected_sources, key=lambda source: (source.folder_name.casefold(), source.folder_name))
    if not root.is_dir():
        raise ValueError("总目录不存在")
    if not sources:
        raise ValueError("没有选择数据来源")
    if not np.isfinite(threshold_pa) or threshold_pa < 0:
        raise ValueError("峰幅值阈值必须为非负有限值")
    for source in sources:
        if not source.label.strip():
            raise ValueError(f"数据集标签不能为空：{source.folder_name}")
        if source.folder.resolve().parent != root:
            raise ValueError(f"数据来源不属于所选总目录：{source.folder_name}")

    output_parent.mkdir(parents=True, exist_ok=True)
    final_dir = _unused_output_path(output_parent)
    temp_dir = output_parent / f".{final_dir.name}.tmp-{uuid.uuid4().hex[:10]}"
    waveform_dir = temp_dir / "waveforms"
    sessions = [(source, load_session(str(source.folder))) for source in sources]
    total = sum(len(session.get("regions", [])) for _, session in sessions)
    skipped: list[SkippedSample] = []
    rows: list[dict] = []
    seen: set[tuple] = set()
    channel_cache: dict[tuple[Path, str], tuple | Exception] = {}
    done = 0
    is_cancelled = cancelled or (lambda: False)

    def report(text: str) -> None:
        if progress is not None:
            progress(done, total, text)

    try:
        waveform_dir.mkdir(parents=True)
        for source, session in sessions:
            regions = sorted(session.get("regions", []), key=_region_sort_key)
            for region in regions:
                if is_cancelled():
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return DatasetBuildSummary(None, 0, tuple(skipped), True)
                description = _region_source(source.folder_name, region)
                sample_temp: Path | None = None
                try:
                    source_path = resolve_region_file(region, source.folder)
                    if source_path is None:
                        raise ValueError("找不到原始 TDMS 文件")
                    source_path = source_path.resolve()
                    requested_channel = str(region.get("channel") or "")
                    cache_key = (source_path, requested_channel)
                    cached = channel_cache.get(cache_key)
                    if cached is None:
                        try:
                            native_values, channel, _ = load_trace(source_path, requested_channel or None)
                            if requested_channel and channel.key != requested_channel:
                                raise ValueError(f"找不到原通道：{requested_channel}")
                            if not np.isfinite(channel.dt) or channel.dt <= 0:
                                raise ValueError("采样间隔必须为有限正数")
                            factor = current_factor(channel.unit)
                            if factor is None:
                                raise ValueError(f"无法将单位 {channel.unit or '未知'} 换算为 pA")
                            current_pa = np.asarray(native_values, dtype=np.float64) * factor
                            finite = current_pa[np.isfinite(current_pa)]
                            if not len(finite):
                                raise ValueError("完整通道没有有限采样值")
                            baseline_pa = float(np.median(finite))
                            cached = (current_pa, channel, float(factor), baseline_pa)
                        except Exception as exc:
                            cached = exc
                        channel_cache[cache_key] = cached
                    if isinstance(cached, Exception):
                        raise cached
                    current_pa, channel, factor, baseline_pa = cached
                    start, end = _strict_region_bounds(region, channel.dt, len(current_pa))
                    dedupe_key = (source.folder.resolve(), source_path, channel.key, start, end)
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    segment = np.asarray(current_pa[start:end], dtype=np.float64)
                    if not np.isfinite(segment).all():
                        raise ValueError("片段包含非有限采样值")
                    features = extract_sample_features(segment - baseline_pa, channel.dt, threshold_pa)

                    sample_id = f"sample_{len(rows) + 1:06d}"
                    sample_path = waveform_dir / f"{sample_id}.npz"
                    sample_temp = waveform_dir / f".{sample_id}.tmp.npz"
                    time_s = np.arange(len(segment), dtype=np.float64) * channel.dt
                    np.savez_compressed(sample_temp, time_s=time_s, current_pa=segment)
                    sample_temp.replace(sample_path)

                    try:
                        source_file = source_path.relative_to(source.folder.resolve()).as_posix()
                    except ValueError:
                        source_file = source_path.name
                    row = {
                        "sample_id": sample_id,
                        "label": source.label.strip(),
                        "source_folder": source.folder_name,
                        "source_file": source_file,
                        "channel": channel.key,
                        "selection_method": "cluster_review" if region.get("cluster_detection") else "manual",
                        "start_index": start,
                        "end_index": end,
                        "start_s": start * channel.dt,
                        "end_s": (end - 1) * channel.dt,
                        "sampling_rate_hz": 1.0 / channel.dt,
                        "native_unit": channel.unit,
                        "native_to_pa_factor": factor,
                        "baseline_pa": baseline_pa,
                        "peak_threshold_pa": float(threshold_pa),
                        "waveform_file": f"waveforms/{sample_id}.npz",
                        "app_version": __version__,
                        "feature_version": FEATURE_VERSION,
                    }
                    row.update(features)
                    rows.append(row)
                except Exception as exc:
                    if sample_temp is not None:
                        sample_temp.unlink(missing_ok=True)
                    skipped.append(SkippedSample(description, str(exc)))
                finally:
                    done += 1
                    report(description)

        if is_cancelled():
            shutil.rmtree(temp_dir, ignore_errors=True)
            return DatasetBuildSummary(None, 0, tuple(skipped), True)
        if not rows:
            raise ValueError("没有可导出的有效样本")
        csv_path = temp_dir / "dataset.csv"
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=DATASET_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        temp_dir.replace(final_dir)
        return DatasetBuildSummary(final_dir, len(rows), tuple(skipped), False)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _mean_std(values: np.ndarray) -> tuple[float, float]:
    if not len(values):
        return 0.0, 0.0
    return float(np.mean(values)), float(np.std(values, ddof=0))


def _integral(values: np.ndarray, dt: float) -> float:
    if len(values) < 2:
        return 0.0
    trapezoid = getattr(np, "trapezoid", None)
    if trapezoid is None:
        trapezoid = np.trapz
    return float(trapezoid(values, dx=dt) * 1000.0)


def _spectrum_features(values: np.ndarray, dt: float) -> dict[str, float]:
    empty = {
        "dominant_frequency_hz": 0.0,
        "spectral_centroid_hz": 0.0,
        "spectral_bandwidth_hz": 0.0,
        "spectral_entropy": 0.0,
        "bandpower_0_100": 0.0,
        "bandpower_100_250": 0.0,
        "bandpower_250_500": 0.0,
        "bandpower_500_1000": 0.0,
    }
    if len(values) < 2:
        return empty

    centered = values - float(np.mean(values))
    spectrum = np.fft.rfft(centered * np.hanning(len(centered)))
    frequencies = np.fft.rfftfreq(len(centered), dt)
    power = np.abs(spectrum) ** 2
    use = (frequencies > 0) & (frequencies <= min(1000.0, 0.5 / dt))
    frequencies = frequencies[use]
    power = power[use]
    total = float(np.sum(power))
    if not len(power) or not np.isfinite(total) or total <= 0:
        return empty

    probabilities = power / total
    centroid = float(np.sum(frequencies * probabilities))
    bandwidth = float(np.sqrt(np.sum(((frequencies - centroid) ** 2) * probabilities)))
    nonzero = probabilities > 0
    entropy = 0.0
    if len(probabilities) > 1:
        entropy = float(-np.sum(probabilities[nonzero] * np.log(probabilities[nonzero])) / np.log(len(probabilities)))

    bands = (
        ("bandpower_0_100", (frequencies >= 0) & (frequencies < 100)),
        ("bandpower_100_250", (frequencies >= 100) & (frequencies < 250)),
        ("bandpower_250_500", (frequencies >= 250) & (frequencies < 500)),
        ("bandpower_500_1000", (frequencies >= 500) & (frequencies <= 1000)),
    )
    result = {
        "dominant_frequency_hz": float(frequencies[int(np.argmax(power))]),
        "spectral_centroid_hz": centroid,
        "spectral_bandwidth_hz": bandwidth,
        "spectral_entropy": entropy,
    }
    result.update({name: float(np.sum(power[mask]) / total) for name, mask in bands})
    return result


def extract_sample_features(
    amplitude_pa: np.ndarray,
    dt: float,
    threshold_pa: float = 10.0,
) -> dict[str, int | float]:
    """Calculate stable numeric features from a baseline-corrected pA segment."""
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
    peak_amplitudes = values[peak_positions] if len(peak_positions) else np.array([], dtype=np.float64)
    peak_widths_ms = (ends - starts).astype(np.float64) * dt * 1000.0
    intervals_ms = np.diff(peak_positions).astype(np.float64) * dt * 1000.0
    peak_amplitude_mean, peak_amplitude_std = _mean_std(peak_amplitudes)
    peak_width_mean, peak_width_std = _mean_std(peak_widths_ms)
    interval_mean, interval_std = _mean_std(intervals_ms)

    result: dict[str, int | float] = {
        "duration_ms": float(max(len(values) - 1, 0) * dt * 1000.0),
        "sample_count": int(len(values)),
        "mean_amplitude_pa": float(np.mean(values)),
        "median_amplitude_pa": float(np.median(values)),
        "std_amplitude_pa": float(np.std(values, ddof=0)),
        "rms_amplitude_pa": float(np.sqrt(np.mean(values ** 2))),
        "max_amplitude_pa": float(np.max(values)),
        "amplitude_iqr_pa": float(np.percentile(values, 75) - np.percentile(values, 25)),
        "positive_area_pa_ms": _integral(np.maximum(values, 0.0), dt),
        "signal_energy_pa2_ms": _integral(values ** 2, dt),
        "peak_count": int(len(starts)),
        "peak_rate_hz": float(len(starts) / (len(values) * dt)),
        "peak_amplitude_mean_pa": peak_amplitude_mean,
        "peak_amplitude_std_pa": peak_amplitude_std,
        "peak_amplitude_max_pa": float(np.max(peak_amplitudes)) if len(peak_amplitudes) else 0.0,
        "peak_width_mean_ms": peak_width_mean,
        "peak_width_std_ms": peak_width_std,
        "interpeak_interval_mean_ms": interval_mean,
        "interpeak_interval_std_ms": interval_std,
    }
    result.update(_spectrum_features(values, dt))
    return result
