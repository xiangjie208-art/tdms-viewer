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
    width = float(parameters["fwhm_ms"])
    threshold = float(parameters["threshold"])
    if not np.isfinite([amplitude, width, threshold]).all() or amplitude <= 0 or width <= 0 or not 1e-6 <= threshold < 1:
        raise ValueError("幅值、窗宽必须为正，分簇阈值须在 0.000001–1 之间（不含 1）。")
    baseline = float(np.median(values)) if parameters["baseline_auto"] else float(parameters["baseline"])
    if not np.isfinite(baseline):
        raise ValueError("基线无效。")
    # Bound temporary FFT arrays; never silently downsample detection input.
    radius = math.ceil(6 * width / (1000 * dt * math.sqrt(8 * math.log(2))))
    if len(values) + 2 * radius > 16_000_000:
        raise ValueError("分析范围或高斯窗过大，请缩小分析区间或窗宽。")
    peaks = event_seeds(values, baseline, amplitude)
    score, kernel = gaussian_score(len(values), peaks, 1 / dt, width)
    starts, ends = true_runs(score > threshold)
    rows = []
    for a, b in zip(starts, ends):
        a, b = int(a), int(b)
        rows.append({"start_index": a + offset, "end_index_exclusive": b + offset,
                     "n_seeds": int(np.searchsorted(peaks, b) - np.searchsorted(peaks, a)),
                     "left_censored": a == 0, "right_censored": b == len(values)})
    return {"rows": rows, "peaks": peaks + offset, "baseline": baseline,
            "parameters": dict(parameters), "kernel": kernel, "offset": offset,
            "end_index_exclusive": offset + len(values)}

def true_runs(mask):
    edge = np.diff(np.r_[False,mask,False].astype(np.int8))
    return np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)

def event_seeds(current, baseline, threshold):
    start, end = true_runs(current-baseline > threshold)
    return np.asarray([s + np.argmax(current[s:e]) for s,e in zip(start,end)], dtype=np.int64)

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
