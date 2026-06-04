from __future__ import annotations

import numpy as np
import pandas as pd

from .config import HC_EV_NM, KB_EV_K


def eqe_absolute(raw: np.ndarray) -> tuple[np.ndarray, float]:
    raw = np.clip(np.asarray(raw, dtype=float), 0.0, None)
    finite = raw[np.isfinite(raw)]
    scale = 100.0 if finite.size and float(np.nanmax(finite)) > 1.0 else 1.0
    return raw / scale, scale

def el_normalized(raw: np.ndarray) -> tuple[np.ndarray, float]:
    raw = np.clip(np.asarray(raw, dtype=float), 0.0, None)
    finite = raw[np.isfinite(raw)]
    scale = float(np.nanmax(finite)) if finite.size and float(np.nanmax(finite)) > 0.0 else 1.0
    return raw / scale, scale

def gaussian_abs(energy_ev: np.ndarray, e_ct: float, lam: float, temp: float) -> np.ndarray:
    thermal = max(4.0 * lam * KB_EV_K * temp, 1e-12)
    return np.exp(-((e_ct + lam - energy_ev) ** 2) / thermal)

def gaussian_el(energy_ev: np.ndarray, e_ct: float, lam: float, temp: float) -> np.ndarray:
    thermal = max(4.0 * lam * KB_EV_K * temp, 1e-12)
    return np.exp(-((e_ct - lam - energy_ev) ** 2) / thermal)

def converted_raw(kind: str, raw: np.ndarray) -> tuple[np.ndarray, float]:
    if kind == "EQE":
        return eqe_absolute(raw)
    return el_normalized(raw)

def reduced_data(kind: str, energy_ev: np.ndarray, raw: np.ndarray) -> np.ndarray:
    y, _ = converted_raw(kind, raw)
    if kind == "EQE":
        return y * energy_ev
    return y / np.maximum(energy_ev, 1e-12)

def raw_from_reduced(kind: str, energy_ev: np.ndarray, reduced: np.ndarray) -> np.ndarray:
    if kind == "EQE":
        return reduced / np.maximum(energy_ev, 1e-12)
    return reduced * energy_ev

def mask_by_nm(df: pd.DataFrame, limits_nm: list[float]) -> np.ndarray:
    lo, hi = sorted(float(v) for v in limits_nm)
    wl = df["wavelength_nm"].to_numpy(dtype=float)
    return (wl >= lo) & (wl <= hi)

def predict_reduced(kind: str, energy_ev: np.ndarray, settings: dict) -> np.ndarray:
    p = {k: float(v["value"]) for k, v in settings["parameters"].items()}
    temp = float(settings.get("temperature_K", 300.0))
    band = gaussian_abs(energy_ev, p["E_CT_eV"], p["lambda_eV"], temp)
    if kind == "EL":
        band = gaussian_el(energy_ev, p["E_CT_eV"], p["lambda_eV"], temp)
    return np.clip(p["A_CT"] * band, 0.0, None)

def add_predictions(eqe: pd.DataFrame, el: pd.DataFrame, settings: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    conversions = {}
    output = []
    for kind, df in (("EQE", eqe.copy()), ("EL", el.copy())):
        if df.empty:
            conversions[kind] = {
                "input_scale": None,
                "raw_label": "EQE absolute" if kind == "EQE" else "EL normalized",
            }
            for col in ("raw_converted", "reduced", "fit_reduced", "fit_raw_converted", "fit_mask"):
                df[col] = []
            output.append(df)
            continue
        e = df["energy_eV"].to_numpy()
        raw = df["raw"].to_numpy()
        raw_converted, scale = converted_raw(kind, raw)
        reduced = reduced_data(kind, e, raw)
        fit_reduced = predict_reduced(kind, e, settings)
        conversions[kind] = {
            "input_scale": scale,
            "raw_label": "EQE absolute" if kind == "EQE" else "EL normalized",
        }
        df["raw_converted"] = raw_converted
        df["reduced"] = reduced
        df["fit_reduced"] = fit_reduced
        df["fit_raw_converted"] = raw_from_reduced(kind, e, fit_reduced)
        df["fit_mask"] = mask_by_nm(df, settings["fit_ranges_nm"][kind])
        output.append(df)
    return output[0], output[1], conversions

def fit_energy_grid(eqe: pd.DataFrame, el: pd.DataFrame | None = None, n: int = 1000) -> np.ndarray:
    energy_sets = [eqe["energy_eV"].to_numpy(dtype=float)]
    if el is not None and not el.empty:
        energy_sets.append(el["energy_eV"].to_numpy(dtype=float))
    finite_sets = [arr[np.isfinite(arr)] for arr in energy_sets if np.any(np.isfinite(arr))]
    if not finite_sets:
        return np.array([], dtype=float)

    e_min = float(min(np.nanmin(arr) for arr in finite_sets))
    if len(finite_sets) > 1:
        e_max = float(min(np.nanmax(arr) for arr in finite_sets))
    else:
        e_max = float(np.nanmax(finite_sets[0]))
    if e_max <= e_min:
        e_max = float(max(np.nanmax(arr) for arr in finite_sets))
    if e_max <= e_min:
        return np.array([e_min], dtype=float)
    return np.linspace(e_min, e_max, int(n))

def build_fit_curves(eqe: pd.DataFrame, el: pd.DataFrame, settings: dict) -> dict:
    fit_energy = fit_energy_grid(eqe, el, 1000)
    fit_wavelength = HC_EV_NM / np.maximum(fit_energy, 1e-12)
    eqe_reduced = predict_reduced("EQE", fit_energy, settings)
    el_reduced = predict_reduced("EL", fit_energy, settings)
    eqe_raw_abs = raw_from_reduced("EQE", fit_energy, eqe_reduced)
    el_raw_norm = raw_from_reduced("EL", fit_energy, el_reduced)
    return {
        "energy_eV": fit_energy,
        "wavelength_nm": fit_wavelength,
        "EQE": {
            "fit_reduced": eqe_reduced,
            "fit_raw_percent": eqe_raw_abs * 100.0,
        },
        "EL": {
            "fit_reduced": el_reduced,
            "fit_raw": el_raw_norm,
        },
    }


