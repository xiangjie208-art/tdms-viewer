from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
from nptdms import TdmsFile


@dataclass(frozen=True)
class ChannelInfo:
    group: str
    channel: str
    length: int
    dt: float
    unit: str

    @property
    def key(self) -> str:
        return f"{self.group}/{self.channel}"

    @property
    def label(self) -> str:
        duration = max(0.0, (self.length - 1) * self.dt)
        return f"{self.key}  |  {self.length:,} 点  |  {duration:.2f} s"


def natural_key(path: Path | str):
    name = Path(path).name
    match = re.search(r"(\d+)(?=\.tdms$)", name, flags=re.IGNORECASE)
    if match:
        return (0, int(match.group(1)), name.lower())
    return (1, 0, name.lower())


def discover_tdms(folder: Path) -> list[Path]:
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".tdms"), key=natural_key)


def inspect_channels(path: Path) -> list[ChannelInfo]:
    with TdmsFile.open(path) as tdms:
        result = []
        for group in tdms.groups():
            for channel in group.channels():
                result.append(ChannelInfo(
                    group=group.name,
                    channel=channel.name,
                    length=len(channel),
                    dt=float(channel.properties.get("wf_increment", 1.0)),
                    unit=str(channel.properties.get("unit_string", "a.u.")),
                ))
    return result


def load_trace(path: Path, requested_key: str | None = None):
    with TdmsFile.open(path) as tdms:
        channels = []
        channel_objects = {}
        for group in tdms.groups():
            for channel in group.channels():
                info = ChannelInfo(
                    group=group.name,
                    channel=channel.name,
                    length=len(channel),
                    dt=float(channel.properties.get("wf_increment", 1.0)),
                    unit=str(channel.properties.get("unit_string", "a.u.")),
                )
                channels.append(info)
                channel_objects[info.key] = channel
        if not channels:
            raise ValueError(f"{path.name} 中没有数据通道")
        selected = next((c for c in channels if c.key == requested_key), None)
        if selected is None:
            selected = max(channels, key=lambda c: c.length)
        values = np.asarray(channel_objects[selected.key][:], dtype=np.float64)
    return values, selected, channels


def minmax_envelope(values: np.ndarray, dt: float, start_index: int = 0, max_bins: int = 12000):
    n = len(values)
    if n == 0:
        return np.array([]), np.array([])
    if n <= max_bins * 2:
        x = (start_index + np.arange(n, dtype=float)) * dt
        return x, values
    bin_size = int(np.ceil(n / max_bins))
    usable = n // bin_size * bin_size
    blocks = values[:usable].reshape(-1, bin_size)
    lows = blocks.min(axis=1)
    highs = blocks.max(axis=1)
    centers = start_index + np.arange(len(blocks), dtype=float) * bin_size + (bin_size - 1) / 2
    x = np.repeat(centers * dt, 2)
    y = np.column_stack((lows, highs)).ravel()
    if usable < n:
        tail = values[usable:]
        center = (start_index + usable + (len(tail) - 1) / 2) * dt
        x = np.r_[x, center, center]
        y = np.r_[y, tail.min(), tail.max()]
    return x, y


def window_values(name: str, n: int):
    if name == "Hamming":
        return np.hamming(n)
    if name == "Blackman":
        return np.blackman(n)
    if name == "矩形窗":
        return np.ones(n)
    return np.hanning(n)


def amplitude_spectrum(values: np.ndarray, dt: float, window_name: str = "Hann"):
    if len(values) < 4:
        raise ValueError("选中区间的数据点太少，无法计算频谱")
    centered = np.asarray(values, dtype=np.float64) - float(np.mean(values))
    window = window_values(window_name, len(centered))
    transformed = np.fft.rfft(centered * window)
    frequency = np.fft.rfftfreq(len(centered), dt)
    amplitude = np.abs(transformed) * 2.0 / max(float(window.sum()), np.finfo(float).eps)
    amplitude[0] *= 0.5
    if len(centered) % 2 == 0:
        amplitude[-1] *= 0.5
    return frequency, amplitude


def welch_psd(values: np.ndarray, dt: float, window_name: str = "Hann", nperseg: int = 65536):
    if len(values) < 16:
        raise ValueError("选中区间的数据点太少，无法计算功率谱")
    values = np.asarray(values, dtype=np.float64)
    nperseg = min(nperseg, len(values))
    if nperseg > 1024:
        nperseg = 2 ** int(np.floor(np.log2(nperseg)))
    step = max(1, nperseg // 2)
    starts = np.arange(0, len(values) - nperseg + 1, step)
    if len(starts) > 64:
        starts = starts[np.linspace(0, len(starts) - 1, 64).astype(int)]
    window = window_values(window_name, nperseg)
    scale = (1.0 / dt) * float(np.sum(window ** 2))
    accumulated = None
    for start in starts:
        segment = values[start:start + nperseg]
        segment = segment - float(np.mean(segment))
        p = np.abs(np.fft.rfft(segment * window)) ** 2 / scale
        if len(p) > 2:
            p[1:-1] *= 2.0
        accumulated = p if accumulated is None else accumulated + p
    psd = accumulated / max(1, len(starts))
    return np.fft.rfftfreq(nperseg, dt), psd


def compute_spectrum(values: np.ndarray, dt: float, mode: str, window_name: str):
    if mode == "功率谱密度 (Welch)":
        return (*welch_psd(values, dt, window_name), "V²/Hz")
    frequency, amplitude = amplitude_spectrum(values, dt, window_name)
    return frequency, amplitude, "V"


def display_spectrum(frequency: np.ndarray, values: np.ndarray, max_bins: int = 10000):
    mask = (frequency > 0) & np.isfinite(values) & (values > 0)
    f, y = frequency[mask], values[mask]
    if len(f) <= max_bins:
        return f, y
    edges = np.geomspace(f[0], f[-1], max_bins + 1)
    indices = np.searchsorted(edges, f, side="right") - 1
    valid = (indices >= 0) & (indices < max_bins)
    peaks = np.full(max_bins, -np.inf)
    np.maximum.at(peaks, indices[valid], y[valid])
    centers = np.sqrt(edges[:-1] * edges[1:])
    keep = np.isfinite(peaks) & (peaks > 0)
    return centers[keep], peaks[keep]


def dominant_peaks(frequency: np.ndarray, values: np.ndarray, count: int = 8, min_frequency: float = 0.1):
    if len(values) < 3:
        return []
    candidates = np.flatnonzero(
        (frequency >= min_frequency)
        & (values > np.roll(values, 1))
        & (values >= np.roll(values, -1))
    )
    if not len(candidates):
        return []
    shortlist_count = min(len(candidates), max(100, count * 50))
    shortlist = candidates[np.argpartition(values[candidates], -shortlist_count)[-shortlist_count:]]
    shortlist = shortlist[np.argsort(values[shortlist])[::-1]]
    chosen = []
    resolution = frequency[1] - frequency[0] if len(frequency) > 1 else 1.0
    min_spacing = max(0.2, resolution * 5)
    for idx in shortlist:
        if all(abs(frequency[idx] - frequency[j]) >= min_spacing for j in chosen):
            chosen.append(int(idx))
            if len(chosen) >= count:
                break
    return [(float(frequency[i]), float(values[i])) for i in chosen]


def trace_statistics(values: np.ndarray):
    if not len(values):
        return {key: float("nan") for key in ("mean", "std", "min", "max", "ptp")}
    return {
        "mean": float(np.mean(values)), "std": float(np.std(values)),
        "min": float(np.min(values)), "max": float(np.max(values)),
        "ptp": float(np.ptp(values)),
    }


def common_log_reference(spectra: list[tuple[np.ndarray, np.ndarray]], bins: int = 1800):
    positive_starts = [f[f > 0][0] for f, _ in spectra if np.any(f > 0)]
    maximums = [f[-1] for f, _ in spectra]
    if not positive_starts:
        raise ValueError("空白数据没有有效频率")
    edges = np.geomspace(max(positive_starts), min(maximums), bins + 1)
    centers = np.sqrt(edges[:-1] * edges[1:])
    rows = []
    for frequency, values in spectra:
        index = np.searchsorted(edges, frequency, side="right") - 1
        valid = (index >= 0) & (index < bins) & np.isfinite(values) & (values > 0)
        row = np.full(bins, -np.inf)
        np.maximum.at(row, index[valid], values[valid])
        row[~np.isfinite(row)] = np.nan
        good = np.isfinite(row) & (row > 0)
        if good.sum() >= 2:
            row[~good] = 10 ** np.interp(
                np.log10(centers[~good]), np.log10(centers[good]), np.log10(row[good])
            )
        rows.append(row)
    matrix = np.asarray(rows)
    return centers, np.nanmedian(matrix, axis=0), np.nanpercentile(matrix, 25, axis=0), np.nanpercentile(matrix, 75, axis=0)
