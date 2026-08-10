from pathlib import Path

import numpy as np
from nptdms import ChannelObject, TdmsWriter

from tdms_fingerprint_viewer.core import (
    amplitude_spectrum,
    discover_tdms,
    load_trace,
    minmax_envelope,
    trace_statistics,
    welch_psd,
)


def test_discover_tdms_uses_final_acquisition_number(tmp_path: Path):
    for name in ("test_10.tdms", "test_2.tdms", "test_0.5_23.tdms", "ignore.txt"):
        (tmp_path / name).touch()
    assert [path.name for path in discover_tdms(tmp_path)] == ["test_2.tdms", "test_10.tdms", "test_0.5_23.tdms"]


def test_amplitude_spectrum_detects_sine_frequency():
    dt = 0.001
    time = np.arange(0, 4, dt)
    values = 2.5 * np.sin(2 * np.pi * 7.0 * time)
    frequency, amplitude = amplitude_spectrum(values, dt, "Hann")
    peak = int(np.argmax(amplitude[1:]) + 1)
    assert frequency[peak] == 7.0
    assert np.isclose(amplitude[peak], 2.5, rtol=0.02)


def test_welch_psd_detects_sine_frequency():
    dt = 0.001
    time = np.arange(0, 8, dt)
    values = np.sin(2 * np.pi * 13.0 * time)
    frequency, psd = welch_psd(values, dt, "Hann", nperseg=4096)
    assert abs(frequency[np.argmax(psd)] - 13.0) < 0.3


def test_minmax_envelope_and_statistics():
    values = np.arange(100_000, dtype=float)
    x, y = minmax_envelope(values, 0.01, max_bins=100)
    assert len(x) == len(y) <= 202
    stats = trace_statistics(np.array([-2.0, 1.0, 4.0]))
    assert stats["mean"] == 1.0
    assert stats["ptp"] == 6.0


def test_load_trace_reads_tdms_metadata(tmp_path: Path):
    path = tmp_path / "synthetic_1.tdms"
    expected = np.linspace(-1, 1, 1000)
    channel = ChannelObject("Current", "Dev1/ai0", expected, properties={"wf_increment": 0.002, "unit_string": "A"})
    with TdmsWriter(path) as writer:
        writer.write_segment([channel])
    values, selected, channels = load_trace(path)
    assert np.allclose(values, expected)
    assert selected.dt == 0.002
    assert selected.unit == "A"
    assert len(channels) == 1
