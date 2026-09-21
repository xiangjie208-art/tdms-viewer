"""Gaussian grouping adapted from the tdms-cluster-extract skill (v1.0.0).

Unit-height kernels; FWHM is an engineering definition, not a paper-code reproduction.
Inputs and outputs remain in the channel native units.
"""

import math

import numpy as np

from scipy.signal import fftconvolve


def find_clusters(values, dt, parameters, offset=0):
    values = np.asarray(values)
    if values.ndim != 1 or not len(values) or np.iscomplexobj(values) or not np.isfinite(values).all():
        raise ValueError("寻簇需要非空且不含 NaN/Inf 的实数通道。")
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError("采样间隔无效。")
    amplitude = float(parameters["amplitude"])
    max_amplitude = float(parameters.get("max_amplitude", np.inf))
    width = float(parameters["fwhm_ms"])
    threshold = float(parameters["threshold"])
    if (not np.isfinite([amplitude, width, threshold]).all() or amplitude <= 0 or width <= 0
            or not 1e-6 <= threshold < 1 or np.isnan(max_amplitude) or max_amplitude <= amplitude):
        raise ValueError("幅值、窗宽必须为正，分簇阈值须在 0.000001–1 之间（不含 1）。")
    min_peaks_value = parameters.get("min_peaks", 1)
    if isinstance(min_peaks_value, bool) or not isinstance(min_peaks_value, (int, float, np.integer, np.floating)):
        raise ValueError("簇内最少峰数必须为正整数。")
    min_peaks_number = float(min_peaks_value)
    if not np.isfinite(min_peaks_number) or min_peaks_number < 1 or not min_peaks_number.is_integer():
        raise ValueError("簇内最少峰数必须为正整数。")
    min_peaks = int(min_peaks_number)
    baseline = float(np.median(values)) if parameters["baseline_auto"] else float(parameters["baseline"])
    if not np.isfinite(baseline):
        raise ValueError("基线无效。")
    # Bound temporary FFT arrays; never silently downsample detection input.
    radius = math.ceil(6 * width / (1000 * dt * math.sqrt(8 * math.log(2))))
    if len(values) + 2 * radius > 16_000_000:
        raise ValueError("分析范围或高斯窗过大，请缩小分析区间或窗宽。")
    candidates, candidate_amplitudes = event_candidates(values, baseline, amplitude)
    automatic = bool(parameters.get("max_amplitude_auto", False))
    supplied_automatic = parameters.get("auto_max_amplitude")
    if automatic and supplied_automatic is not None:
        effective_max_amplitude = float(supplied_automatic)
        maximum_source = parameters.get("auto_maximum_source", "folder_auto")
    elif automatic:
        calculated = automatic_maximum_amplitude(candidate_amplitudes)
        effective_max_amplitude = max_amplitude if calculated is None else calculated
        maximum_source = "manual_fallback" if calculated is None else "auto"
    else:
        effective_max_amplitude = max_amplitude
        maximum_source = "manual"
    if np.isnan(effective_max_amplitude) or effective_max_amplitude <= amplitude:
        raise ValueError("最大有效峰幅值必须高于寻峰幅值。")
    valid = candidate_amplitudes <= effective_max_amplitude
    peaks, rejected_peaks = candidates[valid], candidates[~valid]
    score, kernel = gaussian_score(len(values), peaks, 1 / dt, width)
    starts, ends = true_runs(score > threshold)
    rows = []
    rejected_clusters = 0
    for a, b in zip(starts, ends):
        a, b = int(a), int(b)
        if np.searchsorted(rejected_peaks, b) > np.searchsorted(rejected_peaks, a):
            rejected_clusters += 1
            continue
        n_seeds = int(np.searchsorted(peaks, b) - np.searchsorted(peaks, a))
        if n_seeds < min_peaks:
            continue
        rows.append({"start_index": a + offset, "end_index_exclusive": b + offset,
                     "n_seeds": n_seeds,
                     "left_censored": a == 0, "right_censored": b == len(values)})
    maximum_peak_count = int(parameters.get("auto_maximum_peak_count", len(candidate_amplitudes)))
    result_parameters = dict(parameters, min_peaks=min_peaks,
                             effective_max_amplitude=effective_max_amplitude,
                             maximum_source=maximum_source,
                             maximum_peak_count=maximum_peak_count)
    result_parameters.pop("auto_max_amplitude", None)
    result_parameters.pop("auto_maximum_source", None)
    result_parameters.pop("auto_maximum_peak_count", None)
    return {"rows": rows, "peaks": peaks + offset, "rejected_peaks": rejected_peaks + offset,
            "rejected_clusters": rejected_clusters, "baseline": baseline,
            "parameters": result_parameters, "kernel": kernel, "offset": offset,
            "end_index_exclusive": offset + len(values)}

def true_runs(mask):
    edge = np.diff(np.r_[False,mask,False].astype(np.int8))
    return np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)

def event_seeds(current, baseline, threshold):
    return event_candidates(current, baseline, threshold)[0]


def event_candidates(current, baseline, threshold):
    start, end = true_runs(current-baseline > threshold)
    peaks = np.asarray([s + np.argmax(current[s:e]) for s,e in zip(start,end)], dtype=np.int64)
    return peaks, current[peaks] - baseline


def automatic_maximum_amplitude(amplitudes, minimum_count=20):
    amplitudes = np.asarray(amplitudes, dtype=float)
    amplitudes = amplitudes[np.isfinite(amplitudes) & (amplitudes > 0)]
    if len(amplitudes) < minimum_count:
        return None
    q1, q3 = np.percentile(np.log(amplitudes), [25, 75])
    return float(np.nextafter(np.exp(q3 + 3 * (q3 - q1)), np.inf))

def gaussian_score(n, peaks, fs, fwhm_ms, truncate=6.0):
    sigma = fwhm_ms * fs / 1000 / math.sqrt(8 * math.log(2))
    if sigma < 1:
        raise ValueError('Kernel sigma is below one sample; choose a resolvable window.')
    radius = math.ceil(truncate * sigma)
    kernel = np.exp(-.5*(np.arange(-radius,radius+1)/sigma)**2)
    impulse = np.zeros(n, dtype=float)
    impulse[peaks] = 1
    score = fftconvolve(impulse,kernel,mode='same') if len(peaks) else impulse
    return score, {'sigma_samples':sigma,'fwhm_samples':fwhm_ms*fs/1000,
                   'kernel_radius_samples':radius,'kernel_length_samples':len(kernel),
                   'normalization':'unit height, not unit area','padding':'zero outside observed record'}
