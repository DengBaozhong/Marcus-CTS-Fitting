from __future__ import annotations

import numpy as np
import pandas as pd

from .config import PARAM_LABELS
from .model import add_predictions, build_fit_curves
from .spectra import read_spectrum_optional


def state_payload(settings: dict, metrics: dict | None = None, message: str = "") -> dict:
    settings = clamp_fit_ranges(settings)
    eqe = read_spectrum_optional(settings["eqe_path"])
    el = read_spectrum_optional(settings["el_path"])
    eqe_p, el_p, conversions = add_predictions(eqe, el, settings)
    fit_curves = fit_curves_payload(build_fit_curves(eqe_p, el_p, settings))
    return {
        "settings": settings,
        "metrics": metrics,
        "message": message,
        "conversions": conversions,
        "data_ranges": {
            "EQE": data_range(eqe_p),
            "EL": data_range(el_p),
            "display_energy_eV": display_energy_range(eqe_p, el_p),
        },
        "spectra": {
            "EQE": dataframe_payload(eqe_p),
            "EL": dataframe_payload(el_p),
        },
        "fit_curves": fit_curves,
        "labels": PARAM_LABELS,
    }

def data_range(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "energy_min": None,
            "energy_max": None,
            "wavelength_min": None,
            "wavelength_max": None,
        }
    energy = df["energy_eV"].to_numpy(dtype=float)
    wavelength = df["wavelength_nm"].to_numpy(dtype=float)
    return {
        "energy_min": float(np.nanmin(energy)),
        "energy_max": float(np.nanmax(energy)),
        "wavelength_min": float(np.nanmin(wavelength)),
        "wavelength_max": float(np.nanmax(wavelength)),
    }

def nice_lower_energy(value: float) -> float:
    if not np.isfinite(value) or value <= 0:
        return 0.0
    return max(0.0, float(np.floor(value * 10.0) / 10.0))

def display_energy_range(eqe: pd.DataFrame, el: pd.DataFrame) -> list[float]:
    energy_sets = []
    for df in (eqe, el):
        if not df.empty:
            arr = df["energy_eV"].to_numpy(dtype=float)
            arr = arr[np.isfinite(arr)]
            if arr.size:
                energy_sets.append(arr)
    if not energy_sets:
        return [0.5, 2.0]
    low = nice_lower_energy(float(min(np.nanmin(arr) for arr in energy_sets)))
    if len(energy_sets) > 1:
        high = float(min(np.nanmax(arr) for arr in energy_sets))
    else:
        high = float(np.nanmax(energy_sets[0]))
    if high <= low:
        high = float(max(np.nanmax(arr) for arr in energy_sets))
    return [float(low), float(high)]

def clamp_fit_ranges(settings: dict) -> dict:
    try:
        eqe = read_spectrum_optional(settings["eqe_path"])
        el = read_spectrum_optional(settings["el_path"])
        for kind, df in (("EQE", eqe), ("EL", el)):
            if df.empty:
                continue
            wl_min = float(df["wavelength_nm"].min())
            wl_max = float(df["wavelength_nm"].max())
            current = settings["fit_ranges_nm"].get(kind, [wl_min, wl_max])
            lo, hi = sorted(float(v) for v in current)
            settings["fit_ranges_nm"][kind] = [
                float(np.clip(lo, wl_min, wl_max)),
                float(np.clip(hi, wl_min, wl_max)),
            ]
    except Exception:
        pass
    return settings

def dataframe_payload(df: pd.DataFrame) -> dict:
    return {col: df[col].replace([np.inf, -np.inf], np.nan).where(pd.notnull(df[col]), None).tolist() for col in df.columns}

def array_payload(values: np.ndarray | list[float]) -> list[float | None]:
    series = pd.Series(np.asarray(values, dtype=float))
    return series.replace([np.inf, -np.inf], np.nan).where(pd.notnull(series), None).tolist()

def fit_curves_payload(curves: dict) -> dict:
    return {
        "energy_eV": array_payload(curves["energy_eV"]),
        "wavelength_nm": array_payload(curves["wavelength_nm"]),
        "EQE": {
            "fit_reduced": array_payload(curves["EQE"]["fit_reduced"]),
            "fit_raw_percent": array_payload(curves["EQE"]["fit_raw_percent"]),
        },
        "EL": {
            "fit_reduced": array_payload(curves["EL"]["fit_reduced"]),
            "fit_raw": array_payload(curves["EL"]["fit_raw"]),
        },
    }


