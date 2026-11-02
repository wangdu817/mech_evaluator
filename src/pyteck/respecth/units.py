"""Explicit units: dimensionless mole fractions are not molar concentrations."""
import math

FACTORS = {
    "K": ("temperature", 1.), "Pa": ("pressure", 1.),
    "kPa": ("pressure", 1e3), "MPa": ("pressure", 1e6),
    "bar": ("pressure", 1e5), "atm": ("pressure", 101325.),
    "torr": ("pressure", 101325 / 760),
    "s": ("time", 1.), "ms": ("time", 1e-3),
    "us": ("time", 1e-6), "μs": ("time", 1e-6), "µs": ("time", 1e-6),
    "m3": ("volume", 1.), "cm3": ("volume", 1e-6),
    "L": ("volume", 1e-3), "m": ("length", 1.),
    "cm": ("length", 1e-2), "mm": ("length", 1e-3),
    "m/s": ("speed", 1.), "cm/s": ("speed", .01),
    "mole fraction": ("fraction", 1.), "percent": ("fraction", .01),
    "%": ("fraction", .01), "ppm": ("fraction", 1e-6),
    "unitless": ("dimensionless", 1.), "dimensionless": ("dimensionless", 1.),
    "": ("dimensionless", 1.),
    "L/min": ("flow", 1e-3 / 60), "cm3/min": ("flow", 1e-6 / 60),
    "mol/m3": ("concentration", 1.), "mol/cm3": ("concentration", 1e6),
    "kg/m2/s": ("mass flux", 1.), "g/cm2/s": ("mass flux", 10.),
}
DIMENSIONS = {"temperature": "temperature", "pressure": "pressure",
    "residence time": "time", "ignition delay": "time", "volume": "volume",
    "reactor length": "length", "reactor diameter": "length",
    "laminar burning velocity": "speed", "equivalence ratio": "dimensionless",
    "initial composition": "fraction", "composition": "fraction",
    "time": "time", "distance": "length", "mass flux": "mass flux", "velocity": "speed"}


def to_si(value, units, quantity=""):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"Nonfinite {quantity}")
    if units not in FACTORS:
        raise ValueError(f"Unsupported unit {units!r} for {quantity}")
    dim, factor = FACTORS[units]
    expected = DIMENSIONS.get(quantity)
    if expected and dim != expected:
        raise ValueError(f"Unit {units!r} has wrong dimension for {quantity}")
    if quantity == "concentration" and dim not in ("fraction", "concentration"):
        raise ValueError(f"Unsupported concentration unit {units!r}")
    return value * factor


def from_si(value, units):
    if units not in FACTORS:
        raise ValueError(f"Unsupported display unit {units!r}")
    return value / FACTORS[units][1]
