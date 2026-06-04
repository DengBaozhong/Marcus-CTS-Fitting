from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from .model import mask_by_nm, predict_reduced, reduced_data


def estimate_amplitude(settings: dict, eqe: pd.DataFrame, el: pd.DataFrame) -> dict:
    values = []
    for kind, df in (("EQE", eqe), ("EL", el)):
        e = df["energy_eV"].to_numpy()
        y = reduced_data(kind, e, df["raw"].to_numpy())
        mask = mask_by_nm(df, settings["fit_ranges_nm"][kind])
        if np.any(mask):
            values.append(float(np.nanmax(y[mask])))
    if values:
        settings["parameters"]["A_CT"]["value"] = float(np.clip(np.nanmean(values), 1e-6, 10.0))
    return settings

def fit_ct(settings: dict, eqe: pd.DataFrame, el: pd.DataFrame) -> tuple[dict, dict]:
    names = ["E_CT_eV", "lambda_eV", "A_CT"]

    p0 = np.array([settings["parameters"][name]["value"] for name in names], dtype=float)
    lower = np.array([settings["parameters"][name]["lower"] for name in names], dtype=float)
    upper = np.array([settings["parameters"][name]["upper"] for name in names], dtype=float)
    p0 = np.minimum(np.maximum(p0, lower), upper)

    eqe_mask = mask_by_nm(eqe, settings["fit_ranges_nm"]["EQE"])
    el_mask = mask_by_nm(el, settings["fit_ranges_nm"]["EL"])
    if np.count_nonzero(eqe_mask) < 5:
        raise ValueError("EQE fitting range contains fewer than 5 points.")
    if settings["fit_mode"] == "EQE + EL" and np.count_nonzero(el_mask) < 5:
        raise ValueError("EL fitting range contains fewer than 5 points.")

    eps = 1e-12

    def residual(p: np.ndarray) -> np.ndarray:
        local = json.loads(json.dumps(settings))
        for name, value in zip(names, p):
            local["parameters"][name]["value"] = float(value)

        y_eqe = reduced_data("EQE", eqe["energy_eV"].to_numpy(), eqe["raw"].to_numpy())
        pred_eqe = predict_reduced("EQE", eqe["energy_eV"].to_numpy(), local)
        chunks = [scaled_residual(y_eqe[eqe_mask], pred_eqe[eqe_mask], settings["residual"], eps)]

        if settings["fit_mode"] == "EQE + EL":
            y_el = reduced_data("EL", el["energy_eV"].to_numpy(), el["raw"].to_numpy())
            pred_el = predict_reduced("EL", el["energy_eV"].to_numpy(), local)
            chunks.append(scaled_residual(y_el[el_mask], pred_el[el_mask], settings["residual"], eps))
        return np.concatenate(chunks)

    result = least_squares(
        residual,
        p0,
        bounds=(lower, upper),
        max_nfev=int(settings.get("max_nfev", 20000)),
        x_scale="jac",
    )
    if not result.success:
        raise RuntimeError(result.message)

    for name, value in zip(names, result.x):
        settings["parameters"][name]["value"] = float(value)

    metrics = {
        "success": True,
        "message": str(result.message),
        "cost": float(result.cost),
        "nfev": int(result.nfev),
        "points_eqe": int(np.count_nonzero(eqe_mask)),
        "points_el": int(np.count_nonzero(el_mask)) if settings["fit_mode"] == "EQE + EL" else 0,
    }
    return settings, metrics

def scaled_residual(y: np.ndarray, pred: np.ndarray, mode: str, eps: float) -> np.ndarray:
    y = np.clip(np.asarray(y, dtype=float), 0.0, None)
    pred = np.clip(np.asarray(pred, dtype=float), 0.0, None)
    if mode == "Log":
        floor = max(float(np.nanmax(y)) * 1e-9, eps)
        return np.log10(pred + floor) - np.log10(y + floor)
    scale = max(float(np.nanmax(np.abs(y))), eps)
    return (pred - y) / scale


