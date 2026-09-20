import numpy as np
import pytest

from tdms_fingerprint_viewer.dataset_export import (
    DATASET_COLUMNS,
    FEATURE_VERSION,
    extract_sample_features,
)
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
