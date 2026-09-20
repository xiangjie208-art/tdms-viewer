"""Shared current-unit conversion for analysis workflows."""

CURRENT_TO_PA = {
    "A": 1e12,
    "mA": 1e9,
    "uA": 1e6,
    "µA": 1e6,
    "μA": 1e6,
    "nA": 1e3,
    "pA": 1.0,
}

# Instrument-specific calibration, not a general voltage/current conversion.
VOLTAGE_TO_PA = 1000.0
VOLTAGE_UNITS = {"v", "volt", "volts"}


def current_factor(unit: str) -> float | None:
    """Return the multiplier that converts a supported native unit to pA."""
    text = str(unit).strip()
    if text.casefold() in VOLTAGE_UNITS:
        return VOLTAGE_TO_PA
    return CURRENT_TO_PA.get(text)
