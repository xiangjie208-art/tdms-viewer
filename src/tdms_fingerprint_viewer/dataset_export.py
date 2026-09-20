"""Pure data preparation for machine-learning dataset export."""

from __future__ import annotations

import numpy as np


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
