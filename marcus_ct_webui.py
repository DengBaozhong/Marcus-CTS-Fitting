from __future__ import annotations

import json
import mimetypes
import argparse
import re
import atexit
import shutil
import os
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import plotly
from scipy.optimize import least_squares


HC_EV_NM = 1239.841984
KB_EV_K = 8.617333262145e-5
APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "marcus_ct_settings.json"
RESULTS_DIR = APP_DIR / "fit_results"
UPLOADS_DIR = APP_DIR / "uploaded_spectra"
PLOTLY_JS = Path(plotly.__file__).resolve().parent / "package_data" / "plotly.min.js"


DEFAULT_SETTINGS = {
    "eqe_path": "EQE.csv",
    "el_path": "EL.csv",
    "fit_mode": "EQE + EL",
    "x_mode": "Energy (eV)",
    "y_mode": "Reduced spectra",
    "residual": "Log",
    "max_nfev": 20000,
    "temperature_K": 300.0,
    "fit_ranges_nm": {
        "EQE": [1050.0, 1800.0],
        "EL": [700.0, 1000.0],
    },
    "parameters": {
        "E_CT_eV": {"value": 1.10, "lower": 0.60, "upper": 1.80, "digits": 4},
        "lambda_eV": {"value": 0.18, "lower": 0.01, "upper": 0.80, "digits": 4},
        "A_CT": {"value": 1.0, "lower": 1e-6, "upper": 10.0, "digits": 3},
    },
}


PARAM_LABELS = {
    "E_CT_eV": "E<sub>CT</sub> (eV)",
    "lambda_eV": "lambda (eV)",
    "A_CT": "A<sub>CT</sub>",
}


def deep_update(base: dict, incoming: dict) -> dict:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def migrate_settings(settings: dict) -> dict:
    settings["x_mode"] = "Energy (eV)"
    settings["y_mode"] = "Reduced spectra"
    params = settings.setdefault("parameters", {})
    if "temperature_K" not in settings:
        settings["temperature_K"] = DEFAULT_SETTINGS["temperature_K"]
    params.pop("temperature_K", None)
    if "A_CT" not in params:
        old_a = []
        for key in ("A_EQE", "A_EL"):
            if key in params:
                try:
                    old_a.append(float(params[key].get("value", 1.0)))
                except Exception:
                    pass
        a_value = 1.0 if not old_a else float(np.clip(np.nanmean(old_a), 1e-6, 10.0))
        params["A_CT"] = dict(DEFAULT_SETTINGS["parameters"]["A_CT"], value=a_value)
    params.pop("A_EQE", None)
    params.pop("A_EL", None)
    params.pop("bg_EQE", None)
    params.pop("bg_EL", None)
    for name, default in DEFAULT_SETTINGS["parameters"].items():
        params.setdefault(name, json.loads(json.dumps(default)))
        if "digits" not in params[name]:
            old_step = params[name].pop("step", None)
            params[name]["digits"] = digits_from_legacy_step(old_step, default["digits"])
        else:
            params[name].pop("step", None)
        params[name]["digits"] = int(np.clip(int(params[name]["digits"]), 0, 12))
    if "optimizer" in settings:
        opt = settings.pop("optimizer") or {}
        settings["residual"] = opt.get("residual", settings.get("residual", "Log"))
        settings["max_nfev"] = opt.get("max_nfev", settings.get("max_nfev", 20000))
    return sanitize_settings(settings)


def finite_or(value, fallback: float) -> float:
    try:
        out = float(value)
        return out if np.isfinite(out) else float(fallback)
    except Exception:
        return float(fallback)


def int_at_least(value, minimum: int, fallback: int) -> int:
    try:
        out = int(round(float(value)))
    except Exception:
        out = int(fallback)
    return max(int(minimum), out)


def sanitize_settings(settings: dict) -> dict:
    settings["x_mode"] = "Energy (eV)"
    settings["y_mode"] = "Reduced spectra"
    if settings.get("fit_mode") not in ("EQE", "EQE + EL"):
        settings["fit_mode"] = DEFAULT_SETTINGS["fit_mode"]
    if settings.get("residual") not in ("Log", "Linear"):
        settings["residual"] = DEFAULT_SETTINGS["residual"]

    settings["temperature_K"] = max(1.0, finite_or(settings.get("temperature_K"), DEFAULT_SETTINGS["temperature_K"]))
    settings["max_nfev"] = int_at_least(settings.get("max_nfev"), 1, DEFAULT_SETTINGS["max_nfev"])

    params = settings.setdefault("parameters", {})
    for name, default in DEFAULT_SETTINGS["parameters"].items():
        cfg = params.setdefault(name, json.loads(json.dumps(default)))
        lower = finite_or(cfg.get("lower"), default["lower"])
        upper = finite_or(cfg.get("upper"), default["upper"])
        if lower > upper:
            lower, upper = upper, lower
        value = finite_or(cfg.get("value"), default["value"])
        if value < lower or value > upper:
            value = (lower + upper) / 2.0
        cfg["lower"] = lower
        cfg["upper"] = upper
        cfg["value"] = value
        cfg["digits"] = int_at_least(cfg.get("digits"), 0, default["digits"])
        cfg["digits"] = min(cfg["digits"], 12)
    return settings


def digits_from_legacy_step(step, default: int) -> int:
    if step is None:
        return int(default)
    try:
        text = f"{float(step):.12g}"
        if "e-" in text:
            return min(int(text.split("e-")[1]) + 1, 12)
        if "." in text:
            return min(len(text.rstrip("0").split(".")[1]) + 1, 12)
    except Exception:
        pass
    return int(default)


def load_settings() -> dict:
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    if SETTINGS_PATH.exists():
        try:
            saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            deep_update(settings, saved)
        except Exception:
            pass
    return migrate_settings(settings)


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def clear_uploaded_spectra() -> None:
    if UPLOADS_DIR.exists():
        shutil.rmtree(UPLOADS_DIR, ignore_errors=True)


def safe_upload_name(kind: str, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix != ".csv":
        suffix = ".csv"
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename or kind).stem).strip("._")
    if not stem:
        stem = kind
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{kind}_{timestamp}_{stem}{suffix}"


def save_uploaded_csv(kind: str, filename: str, content: str) -> str:
    if kind not in ("EQE", "EL"):
        raise ValueError("Upload kind must be EQE or EL.")
    UPLOADS_DIR.mkdir(exist_ok=True)
    rel_path = Path("uploaded_spectra") / safe_upload_name(kind, filename)
    abs_path = APP_DIR / rel_path
    abs_path.write_text(content, encoding="utf-8-sig")
    read_spectrum(str(rel_path))
    return str(rel_path).replace("\\", "/")


def safe_filename_prefix(prefix: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", str(prefix).strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("._-")
    return cleaned or "marcus_ct_fit"


def read_spectrum(path: str) -> pd.DataFrame:
    df = pd.read_csv(APP_DIR / path)
    if df.shape[1] < 2:
        raise ValueError(f"{path} must contain at least two columns.")
    out = pd.DataFrame(
        {
            "wavelength_nm": pd.to_numeric(df.iloc[:, 0], errors="coerce"),
            "raw": pd.to_numeric(df.iloc[:, 1], errors="coerce"),
        }
    ).dropna()
    out = out[(out["wavelength_nm"] > 0) & np.isfinite(out["raw"])].copy()
    out["energy_eV"] = HC_EV_NM / out["wavelength_nm"].to_numpy(dtype=float)
    return out.sort_values("wavelength_nm").reset_index(drop=True)


def empty_spectrum() -> pd.DataFrame:
    return pd.DataFrame({"wavelength_nm": [], "raw": [], "energy_eV": []})


def read_spectrum_optional(path: str) -> pd.DataFrame:
    if not path:
        return empty_spectrum()
    try:
        spectrum_path = APP_DIR / path
        if not spectrum_path.exists():
            return empty_spectrum()
        return read_spectrum(path)
    except Exception:
        return empty_spectrum()


def require_spectrum_file(settings: dict, kind: str) -> None:
    path = settings.get(f"{kind.lower()}_path", "")
    if not path or not (APP_DIR / path).exists():
        raise ValueError(f"Please upload a valid {kind} CSV file first.")


def require_ready_for_mode(settings: dict) -> None:
    require_spectrum_file(settings, "EQE")
    if settings.get("fit_mode") == "EQE + EL":
        require_spectrum_file(settings, "EL")


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


def padded_series(values: np.ndarray | pd.Series | list[float], length: int) -> pd.Series:
    series = pd.Series(np.asarray(values, dtype=float))
    if len(series) < length:
        series = series.reindex(range(length))
    return series.reset_index(drop=True)


def save_csv(settings: dict, metrics: dict | None, filename_prefix: str = "") -> Path:
    require_ready_for_mode(settings)
    eqe = read_spectrum(settings["eqe_path"])
    el = read_spectrum(settings["el_path"]) if settings["fit_mode"] == "EQE + EL" else read_spectrum_optional(settings.get("el_path", ""))
    eqe_p, el_p, conversions = add_predictions(eqe, el, settings)
    fit_curves = build_fit_curves(eqe_p, el_p, settings)

    columns = {
        "eqe_wavelength_nm": eqe_p["wavelength_nm"].to_numpy(dtype=float),
        "eqe_energy_eV": eqe_p["energy_eV"].to_numpy(dtype=float),
        "raw_eqe_percent": eqe_p["raw_converted"].to_numpy(dtype=float) * 100.0,
        "reduced_eqe": eqe_p["reduced"].to_numpy(dtype=float),
        "fitted_eqe_wavelength_nm": fit_curves["wavelength_nm"],
        "fitted_eqe_energy_eV": fit_curves["energy_eV"],
        "fitted_eqe_percent": fit_curves["EQE"]["fit_raw_percent"],
        "fitted_reduced_eqe": fit_curves["EQE"]["fit_reduced"],
    }

    if settings["fit_mode"] == "EQE + EL":
        columns.update(
            {
                "el_wavelength_nm": el_p["wavelength_nm"].to_numpy(dtype=float),
                "el_energy_eV": el_p["energy_eV"].to_numpy(dtype=float),
                "raw_el": el_p["raw"].to_numpy(dtype=float),
                "reduced_el": el_p["reduced"].to_numpy(dtype=float),
                "fitted_el_wavelength_nm": fit_curves["wavelength_nm"],
                "fitted_el_energy_eV": fit_curves["energy_eV"],
                "fitted_el": fit_curves["EL"]["fit_raw"],
                "fitted_reduced_el": fit_curves["EL"]["fit_reduced"],
            }
        )

    length = max(len(values) for values in columns.values())
    out = pd.DataFrame({name: padded_series(values, length) for name, values in columns.items()})
    fit_parameter = pd.Series([np.nan] * length, dtype=object)
    fit_value = pd.Series([np.nan] * length, dtype=object)
    parameter_rows = [
        ("ECT_eV", settings["parameters"]["E_CT_eV"]["value"]),
        ("lambda_eV", settings["parameters"]["lambda_eV"]["value"]),
        ("ACT", settings["parameters"]["A_CT"]["value"]),
    ]
    for idx, (name, value) in enumerate(parameter_rows):
        if idx < length:
            fit_parameter.iloc[idx] = name
            fit_value.iloc[idx] = value
    out["fit_parameter"] = fit_parameter
    out["fit_value"] = fit_value
    RESULTS_DIR.mkdir(exist_ok=True)
    prefix = safe_filename_prefix(filename_prefix)
    path = RESULTS_DIR / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return path


class AppState:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.metrics = None


APP_STATE = AppState()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_text(INDEX_HTML, "text/html; charset=utf-8")
        elif path == "/plotly.min.js":
            wrapped = (
                b"var module=undefined;var exports=undefined;\n"
                + PLOTLY_JS.read_bytes()
                + b"\nwindow.Plotly=window.Plotly||window.moduleName;\n"
            )
            self.send_bytes(wrapped, "application/javascript")
        elif path == "/api/state":
            self.send_json(state_payload(APP_STATE.settings, APP_STATE.metrics))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/update":
                APP_STATE.settings = sanitize_settings(migrate_settings(payload.get("settings", APP_STATE.settings)))
                save_settings(APP_STATE.settings)
                self.send_json(state_payload(APP_STATE.settings, APP_STATE.metrics, "Settings updated."))
            elif path == "/api/upload":
                kind = payload.get("kind")
                rel_path = save_uploaded_csv(kind, payload.get("filename", ""), payload.get("content", ""))
                APP_STATE.settings[f"{str(kind).lower()}_path"] = rel_path
                APP_STATE.metrics = None
                save_settings(APP_STATE.settings)
                self.send_json(state_payload(APP_STATE.settings, APP_STATE.metrics, f"{kind} uploaded: {rel_path}"))
            elif path == "/api/fit":
                APP_STATE.settings = sanitize_settings(migrate_settings(payload.get("settings", APP_STATE.settings)))
                require_ready_for_mode(APP_STATE.settings)
                APP_STATE.settings, APP_STATE.metrics = fit_ct(
                    APP_STATE.settings,
                    read_spectrum(APP_STATE.settings["eqe_path"]),
                    read_spectrum(APP_STATE.settings["el_path"])
                    if APP_STATE.settings["fit_mode"] == "EQE + EL"
                    else read_spectrum_optional(APP_STATE.settings.get("el_path", "")),
                )
                save_settings(APP_STATE.settings)
                self.send_json(state_payload(APP_STATE.settings, APP_STATE.metrics, "Fit completed."))
            elif path == "/api/save":
                APP_STATE.settings = sanitize_settings(migrate_settings(payload.get("settings", APP_STATE.settings)))
                save_settings(APP_STATE.settings)
                path_out = save_csv(APP_STATE.settings, APP_STATE.metrics, payload.get("filename_prefix", ""))
                self.send_json(state_payload(APP_STATE.settings, APP_STATE.metrics, f"Saved: {path_out}"))
            else:
                self.send_error(404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body: bytes, content_type: str | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(self.path)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


INDEX_HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Marcus CT Spectra Fit</title>
  <script src="/plotly.min.js"></script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b0f14;
      --panel: #111821;
      --panel2: #151d28;
      --line: #2b3545;
      --text: #e8edf5;
      --muted: #9aa8bb;
      --blue: #3b82f6;
      --orange: #d65a31;
      --red: #ff4d4f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      background: linear-gradient(180deg, #0b0f14 0%, #101720 42%, #0c1118 100%);
      color: var(--text);
      font-size: 16px;
    }
    .app { display: grid; grid-template-columns: 320px minmax(0, 1fr); min-height: 100vh; }
    aside {
      border-right: 1px solid var(--line);
      background: #0f141b;
      padding: 18px;
      overflow: auto;
      max-height: 100vh;
    }
    main { padding: 24px 28px 32px; min-width: 0; }
    h1 { margin: 0; font-size: 38px; letter-spacing: 0; }
    h2 { font-size: 18px; margin: 24px 0 12px; color: #f8fafc; }
    label { display: block; color: var(--muted); font-size: 14px; margin-bottom: 7px; }
    .subtitle { color: #bdd0ea; margin: 8px 0 22px; max-width: 980px; font-size: 18px; line-height: 1.55; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .seg { display: grid; grid-template-columns: 1fr 1fr; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
    .seg button, button {
      background: #151b24;
      color: var(--text);
      border: 1px solid var(--line);
      border-radius: 7px;
      height: 38px;
      cursor: pointer;
      font-weight: 650;
      font-size: 15px;
    }
    .seg button { border: 0; border-radius: 0; }
    .seg button.active { background: var(--red); color: white; }
    button.primary { background: var(--red); border-color: var(--red); color: white; }
    button:hover { filter: brightness(1.08); }
    input, select {
      width: 100%;
      height: 42px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #171d27;
      color: var(--text);
      padding: 0 10px;
      outline: none;
      font-size: 15px;
    }
    input[type="file"] {
      display: none;
    }
    .dropzone {
      border: 1px dashed #52627a;
      background: #121a24;
      border-radius: 8px;
      min-height: 86px;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 12px;
      text-align: center;
      cursor: pointer;
      transition: border-color 0.15s ease, background 0.15s ease;
    }
    .dropzone:hover,
    .dropzone.dragover {
      border-color: #8fb4ff;
      background: #172234;
    }
    .dropzone strong {
      display: block;
      color: #f8fafc;
      font-size: 15px;
      margin-bottom: 4px;
    }
    .dropzone span {
      color: var(--muted);
      font-size: 13px;
    }
    input:focus, select:focus { border-color: #64748b; }
    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(17, 24, 33, 0.8);
      padding: 14px;
      margin-bottom: 16px;
    }
    .params {
      display: grid;
      grid-template-columns: 1.25fr repeat(4, 1fr);
      gap: 10px;
      align-items: center;
    }
    .params .head { color: var(--muted); font-size: 14px; }
    .param-name { font-weight: 700; }
    .toolbar { display: grid; grid-template-columns: repeat(3, minmax(140px, 1fr)); gap: 12px; margin: 14px 0; }
    .cards { display: grid; grid-template-columns: repeat(4, minmax(130px, 1fr)); gap: 12px; margin-bottom: 14px; }
    .card {
      border: 1px solid var(--line);
      background: #151b24;
      border-radius: 8px;
      padding: 12px 14px;
      min-height: 70px;
    }
    .card small { color: var(--muted); }
    .card small { font-size: 14px; }
    .card strong { display: block; margin-top: 6px; font-size: 21px; color: #f8fafc; }
    #plot {
      height: 680px;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: #0f141b;
    }
    .hint {
      color: var(--muted);
      font-size: 15px;
      margin-top: 8px;
      line-height: 1.55;
    }
    .mini {
      color: var(--muted);
      font-size: 13px;
      margin-top: 6px;
      word-break: break-all;
    }
    .message {
      min-height: 24px;
      color: #a7f3d0;
      font-size: 15px;
      margin: 8px 0 0;
    }
    .error { color: #fecaca; }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <h2>Data</h2>
      <label>EQE CSV</label>
      <div class="dropzone" id="EQE_drop">
        <div><strong>Choose or drop EQE CSV</strong><span id="EQE_file_label">No file loaded</span></div>
      </div>
      <input id="EQE_file" type="file" accept=".csv,text/csv">
      <div class="mini" id="EQE_path"></div>
      <label style="margin-top:12px">EL CSV</label>
      <div class="dropzone" id="EL_drop">
        <div><strong>Choose or drop EL CSV</strong><span id="EL_file_label">No file loaded</span></div>
      </div>
      <input id="EL_file" type="file" accept=".csv,text/csv">
      <div class="mini" id="EL_path"></div>

      <h2>View</h2>
      <label>Fitting mode</label>
      <div class="seg" data-key="fit_mode">
        <button data-value="EQE">EQE</button>
        <button data-value="EQE + EL">EQE + EL</button>
      </div>

      <h2>Ranges</h2>
      <div class="row">
        <div><label>EQE min (nm)</label><input id="EQE_min" type="number" step="1"></div>
        <div><label>EQE max (nm)</label><input id="EQE_max" type="number" step="1"></div>
      </div>
      <div class="row" style="margin-top:10px">
        <div><label>EL min (nm)</label><input id="EL_min" type="number" step="1"></div>
        <div><label>EL max (nm)</label><input id="EL_max" type="number" step="1"></div>
      </div>
      <div class="hint">Drag the vertical range lines directly in the plot. EQE lines are blue; EL lines appear in EQE + EL mode.</div>

      <h2>Optimizer</h2>
      <label>Temperature T (K)</label>
      <input id="temperature_K" type="number" step="1" min="1">
      <label style="margin-top:10px">Residual</label>
      <select id="residual"><option>Log</option><option>Linear</option></select>
      <label style="margin-top:10px">Max function evaluations</label>
      <input id="max_nfev" type="number" step="1000" min="1000">

      <h2>Save</h2>
      <label>CSV filename prefix</label>
      <input id="filename_prefix" type="text" placeholder="marcus_ct_fit">
      <div class="hint">Leave blank to use the default prefix. This field resets when the UI is opened.</div>
    </aside>
    <main>
      <h1>Marcus CT Spectra Fit</h1>
      <div class="subtitle">Use EQE and electroluminescence spectra with Marcus charge-transfer theory to fit the charge-transfer-state energy and reorganization energy.</div>

      <div class="panel">
        <div class="params" id="params"></div>
      </div>

      <div class="toolbar">
        <button class="primary" id="fit">Fit</button>
        <button id="save">Save CSV</button>
        <button id="refresh">Refresh</button>
      </div>

      <div class="cards" id="cards"></div>
      <div id="plot"></div>
      <div class="hint">Reduced spectra use EQE_abs × E and EL_norm / E on one shared y-axis. EQE values above 1 are treated as percent and divided by 100; EL is normalized to its own peak before reduction.</div>
      <div class="message" id="message"></div>
    </main>
  </div>

  <script>
    const HC = 1239.841984;
    const PlotlyLib = window.Plotly || window.moduleName;
    let state = null;
    let suppressRelayout = false;
    let relayoutBound = false;
    const $ = (id) => document.getElementById(id);

    const nmToX = (nm) => HC / nm;
    const xToNm = (x) => HC / x;
    const axisRange = (kind) => state.data_ranges[kind];

    function hasSpectrum(kind) {
      return Boolean(state?.spectra?.[kind]?.energy_eV?.length);
    }

    function hasRange(kind) {
      const r = axisRange(kind);
      return r && Number.isFinite(Number(r.wavelength_min)) && Number.isFinite(Number(r.wavelength_max));
    }

    function clamp(value, lo, hi) {
      return Math.min(Math.max(value, lo), hi);
    }

    function clampNm(kind, nm) {
      const r = axisRange(kind);
      if (!hasRange(kind)) return Number(nm);
      return clamp(nm, r.wavelength_min, r.wavelength_max);
    }

    function clampRangeNm(kind, range) {
      const a = clampNm(kind, Number(range[0]));
      const b = clampNm(kind, Number(range[1]));
      return [a, b].sort((x, y) => x - y);
    }

    function api(path, body = null) {
      return new Promise((resolve, reject) => {
        const req = new XMLHttpRequest();
        req.open(body ? 'POST' : 'GET', path, true);
        req.setRequestHeader('Accept', 'application/json');
        if (body) req.setRequestHeader('Content-Type', 'application/json');
        req.onload = () => {
          let data = null;
          try { data = JSON.parse(req.responseText || '{}'); }
          catch (err) { reject(err); return; }
          if (req.status < 200 || req.status >= 300 || data.error) {
            reject(new Error(data.error || req.statusText || 'Request failed'));
          } else {
            resolve(data);
          }
        };
        req.onerror = () => reject(new Error('Request failed'));
        req.send(body ? JSON.stringify(body) : null);
      });
    }

    async function load() {
      state = await api('/api/state');
      renderAll();
    }

    function readSettingsFromDom() {
      const s = structuredClone(state.settings);
      for (const key of ['fit_mode']) {
        const active = document.querySelector(`.seg[data-key="${key}"] button.active`);
        if (active) s[key] = active.dataset.value;
      }
      s.x_mode = 'Energy (eV)';
      s.y_mode = 'Reduced spectra';
      if (hasSpectrum('EQE')) {
        s.fit_ranges_nm.EQE = clampRangeNm('EQE', [parseFloat($('EQE_min').value), parseFloat($('EQE_max').value)]);
      }
      if (hasSpectrum('EL')) {
        s.fit_ranges_nm.EL = clampRangeNm('EL', [parseFloat($('EL_min').value), parseFloat($('EL_max').value)]);
      }
      s.temperature_K = intAtLeast($('temperature_K').value, 1, 300);
      s.residual = $('residual').value;
      s.max_nfev = intAtLeast($('max_nfev').value, 1, 20000);
      for (const [name, cfg] of Object.entries(s.parameters)) {
        for (const field of ['value','lower','upper','digits']) {
          const el = document.getElementById(`${name}_${field}`);
          if (el) cfg[field] = field === 'digits' ? parseInt(el.value || '4', 10) : parseFloat(el.value);
        }
        sanitizeParameterConfig(cfg);
      }
      return s;
    }

    async function updateServer(render = true) {
      state = await api('/api/update', {settings: readSettingsFromDom()});
      if (render) renderAll();
    }

    async function updateSettings(settings, render = true) {
      state = await api('/api/update', {settings});
      if (render) renderAll();
    }

    function renderAll() {
      renderControls();
      renderCards();
      renderPlot();
      setMessage(state.message || '');
    }

    function renderControls() {
      document.querySelectorAll('.seg').forEach(group => {
        const key = group.dataset.key;
        group.querySelectorAll('button').forEach(btn => {
          btn.classList.toggle('active', btn.dataset.value === state.settings[key]);
        });
      });
      const eqeLoaded = hasSpectrum('EQE');
      const elLoaded = hasSpectrum('EL');
      $('EQE_file_label').textContent = eqeLoaded ? fileNameFromPath(state.settings.eqe_path) : 'No file loaded';
      $('EL_file_label').textContent = elLoaded ? fileNameFromPath(state.settings.el_path) : 'No file loaded';
      $('EQE_path').textContent = eqeLoaded ? state.settings.eqe_path : '';
      $('EL_path').textContent = elLoaded ? state.settings.el_path : '';
      if (eqeLoaded) {
        state.settings.fit_ranges_nm.EQE = clampRangeNm('EQE', state.settings.fit_ranges_nm.EQE);
        $('EQE_min').value = state.settings.fit_ranges_nm.EQE[0].toFixed(3);
        $('EQE_max').value = state.settings.fit_ranges_nm.EQE[1].toFixed(3);
      } else {
        $('EQE_min').value = '';
        $('EQE_max').value = '';
      }
      if (elLoaded) {
        state.settings.fit_ranges_nm.EL = clampRangeNm('EL', state.settings.fit_ranges_nm.EL);
        $('EL_min').value = state.settings.fit_ranges_nm.EL[0].toFixed(3);
        $('EL_max').value = state.settings.fit_ranges_nm.EL[1].toFixed(3);
      } else {
        $('EL_min').value = '';
        $('EL_max').value = '';
      }
      const elEnabled = state.settings.fit_mode === 'EQE + EL';
      $('EQE_min').disabled = !eqeLoaded;
      $('EQE_max').disabled = !eqeLoaded;
      $('EL_min').disabled = !elEnabled || !elLoaded;
      $('EL_max').disabled = !elEnabled || !elLoaded;
      $('temperature_K').value = formatByStep(state.settings.temperature_K ?? 300, 1);
      $('residual').value = state.settings.residual;
      $('max_nfev').value = state.settings.max_nfev;

      const p = state.settings.parameters;
      const labels = state.labels;
      let html = '<div class="head">Parameter</div><div class="head">Initial / fitted</div><div class="head">Lower</div><div class="head">Upper</div><div class="head">Digits</div>';
      for (const [name, cfg] of Object.entries(p)) {
        html += `<div class="param-name">${labels[name] || name}</div>`;
        for (const field of ['value','lower','upper','digits']) {
          const value = field === 'value' ? formatByDigits(cfg[field], cfg.digits) : (field === 'digits' ? String(cfg[field]) : formatPlain(cfg[field]));
          const step = field === 'digits' ? '1' : 'any';
          const min = field === 'digits' ? ' min="0" max="12"' : '';
          html += `<input id="${name}_${field}" type="number" step="${step}"${min} value="${value}">`;
        }
      }
      $('params').innerHTML = html;
      $('params').querySelectorAll('input').forEach(input => input.addEventListener('change', () => updateServer(false)));
    }

    function renderCards() {
      const p = state.settings.parameters;
      const items = [
        ['E<sub>CT</sub>', `${formatByDigits(p.E_CT_eV.value, p.E_CT_eV.digits)} eV`],
        ['lambda', `${formatByDigits(p.lambda_eV.value, p.lambda_eV.digits)} eV`],
        ['T fixed', `${formatByStep(state.settings.temperature_K ?? 300, 1)} K`],
        ['A<sub>CT</sub>', `${formatByDigits(p.A_CT.value, p.A_CT.digits)}`],
      ];
      $('cards').innerHTML = items.map(([k,v]) => `<div class="card"><small>${k}</small><strong>${v}</strong></div>`).join('');
    }

    function fileNameFromPath(path) {
      return String(path || '').split(/[\\/]/).pop() || 'No file loaded';
    }

    function formatByDigits(value, digits) {
      const number = Number(value);
      const places = Math.min(Math.max(parseInt(digits ?? 4, 10), 0), 12);
      if (!Number.isFinite(number)) return '';
      return number.toFixed(places);
    }

    function decimalsFromStep(step) {
      const text = String(step ?? '');
      if (text.includes('e-')) return parseInt(text.split('e-')[1], 10);
      if (text.includes('E-')) return parseInt(text.split('E-')[1], 10);
      const dot = text.indexOf('.');
      return dot >= 0 ? text.length - dot - 1 : 0;
    }

    function formatByStep(value, step, extra = 0) {
      const number = Number(value);
      if (!Number.isFinite(number)) return '';
      const digits = Math.min(Math.max(decimalsFromStep(step) + extra, 0), 12);
      return number.toFixed(digits);
    }

    function formatPlain(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return '';
      if (number !== 0 && Math.abs(number) < 1e-4) return number.toExponential(3);
      return String(Number(number.toPrecision(10)));
    }

    function intAtLeast(value, min, fallback) {
      const parsed = Math.round(Number(value));
      if (!Number.isFinite(parsed)) return fallback;
      return Math.max(min, parsed);
    }

    function finiteOr(value, fallback) {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function sanitizeParameterConfig(cfg) {
      let lower = finiteOr(cfg.lower, 0);
      let upper = finiteOr(cfg.upper, lower);
      if (lower > upper) [lower, upper] = [upper, lower];
      let value = finiteOr(cfg.value, (lower + upper) / 2);
      if (value < lower || value > upper) value = (lower + upper) / 2;
      cfg.lower = lower;
      cfg.upper = upper;
      cfg.value = value;
      cfg.digits = Math.min(intAtLeast(cfg.digits, 0, 4), 12);
    }

    function countMask(kind) {
      const s = state.spectra[kind];
      return s.fit_mask.filter(Boolean).length;
    }

    function trace(kind, fit=false) {
      const s = state.spectra[kind];
      const x = fit ? state.fit_curves.energy_eV : s.energy_eV;
      const y = fit ? state.fit_curves[kind].fit_reduced : s.reduced;
      const color = kind === 'EQE' ? '#3b82f6' : '#d65a31';
      return {
        x, y,
        type: 'scatter',
        mode: fit ? 'lines' : 'markers',
        name: `${kind} ${fit ? 'fit' : 'data'}`,
        yaxis: 'y',
        marker: {size: kind === 'EQE' ? 7 : 5, color, opacity: fit ? 1 : 0.82},
        line: {width: 3, color},
        hovertemplate: `${kind} ${fit ? 'fit' : 'data'}<br>%{x:.5g}<br>%{y:.5g}<extra></extra>`
      };
    }

    function visibleTrace(kind, fit=false) {
      const base = trace(kind, fit);
      const [emin, emax] = state.data_ranges.display_energy_eV;
      const xValues = fit ? state.fit_curves.energy_eV : state.spectra[kind].energy_eV;
      const keep = xValues.map(e => Number(e) >= emin && Number(e) <= emax);
      base.x = base.x.filter((_, i) => keep[i]);
      base.y = base.y.filter((_, i) => keep[i]);
      return base;
    }

    function positiveRange(values) {
      const positives = values
        .map(Number)
        .filter(v => Number.isFinite(v) && v > 0);
      if (!positives.length) return [-12, 0];
      const minV = Math.min(...positives);
      const maxV = Math.max(...positives);
      let lower = Math.floor(Math.log10(minV));
      let upper = Math.ceil(Math.log10(maxV));
      if (lower === upper) {
        lower -= 1;
        upper += 1;
      }
      return [lower, upper];
    }

    function dataYRange(kind = null) {
      const values = [...state.spectra.EQE.reduced];
      if (state.settings.fit_mode === 'EQE + EL') values.push(...state.spectra.EL.reduced);
      return positiveRange(values);
    }

    function renderPlot() {
      const ranges = state.settings.fit_ranges_nm;
      const yRange = dataYRange();
      const [displayEmin, displayEmax] = state.data_ranges.display_energy_eV;
      const xRange = [displayEmin, displayEmax];
      const shapes = [];
      if (hasSpectrum('EQE')) {
        const e0 = nmToX(ranges.EQE[0]), e1 = nmToX(ranges.EQE[1]);
        const eqeX = [Math.min(e0,e1), Math.max(e0,e1)];
        shapes.push(
          band(eqeX[0], eqeX[1], 'rgba(59,130,246,0.10)'),
          line(eqeX[0], '#3b82f6', 'EQE lower'),
          line(eqeX[1], '#3b82f6', 'EQE upper')
        );
      }
      if (state.settings.fit_mode === 'EQE + EL' && hasSpectrum('EL')) {
        const l0 = nmToX(ranges.EL[0]), l1 = nmToX(ranges.EL[1]);
        const elX = [Math.min(l0,l1), Math.max(l0,l1)];
        shapes.push(
          band(elX[0], elX[1], 'rgba(214,90,49,0.11)'),
          line(elX[0], '#d65a31', 'EL lower'),
          line(elX[1], '#d65a31', 'EL upper')
        );
      }
      const layout = {
        template: 'plotly_dark',
        paper_bgcolor: '#0f141b',
        plot_bgcolor: '#0f141b',
        font: {color: '#e8edf5', size: 15},
        margin: {l: 82, r: 26, t: 26, b: 86},
        automargin: true,
        legend: {orientation: 'h', y: 1.08, x: 0},
        hovermode: 'x unified',
        dragmode: 'pan',
        shapes,
        xaxis: {
          title: {text: 'Energy (eV)'},
          automargin: true,
          title_standoff: 18,
          range: xRange,
          gridcolor: '#303846',
          zerolinecolor: '#3b4658'
        },
        yaxis: {
          title: {text: 'Reduced spectra'},
          automargin: true,
          title_standoff: 18,
          type: 'log',
          range: yRange,
          exponentformat: 'e',
          showexponent: 'all',
          tickformat: '.1e',
          gridcolor: '#303846',
          zerolinecolor: '#3b4658'
        }
      };
      suppressRelayout = true;
      if (!PlotlyLib) {
        setMessage('Plotly failed to load. Please refresh the page.', true);
        return;
      }
      const traces = [];
      if (hasSpectrum('EQE')) {
        traces.push(visibleTrace('EQE'), visibleTrace('EQE', true));
      }
      if (state.settings.fit_mode === 'EQE + EL' && hasSpectrum('EL')) {
        traces.push(visibleTrace('EL'), visibleTrace('EL', true));
      }
      PlotlyLib.react('plot', traces, layout, {
        responsive: true,
        editable: true,
        edits: {shapePosition: true, annotationPosition: false, legendPosition: false, titleText: false},
        displaylogo: false
      }).then((gd) => {
        if (!relayoutBound && gd && typeof gd.on === 'function') {
          gd.on('plotly_relayout', applyShapeRelayout);
          relayoutBound = true;
        }
        suppressRelayout = false;
      });
    }

    function band(x0, x1, fillcolor) {
      return {type:'rect', xref:'x', yref:'paper', x0, x1, y0:0, y1:1, fillcolor, line:{width:0}, layer:'below', editable:false};
    }
    function line(x, color, name) {
      return {type:'line', xref:'x', yref:'paper', x0:x, x1:x, y0:0, y1:1, line:{color, width:3, dash:'dash'}, editable:true, name};
    }
    function setMessage(text, error=false) {
      $('message').textContent = text;
      $('message').classList.toggle('error', error);
    }

    function applyShapeRelayout(ev) {
      if (suppressRelayout) return;
      const s = state.settings;
      const xs = {
        eqeLo: readShapeX(ev, 1),
        eqeHi: readShapeX(ev, 2),
        elLo: readShapeX(ev, 4),
        elHi: readShapeX(ev, 5)
      };
      let changed = false;
      if (hasSpectrum('EQE') && (xs.eqeLo !== null || xs.eqeHi !== null)) {
        const current = s.fit_ranges_nm.EQE.map(nmToX).sort((a,b)=>a-b);
        const newX = [xs.eqeLo ?? current[0], xs.eqeHi ?? current[1]];
        s.fit_ranges_nm.EQE = clampRangeNm('EQE', newX.map(xToNm));
        changed = true;
      }
      if (hasSpectrum('EL') && (xs.elLo !== null || xs.elHi !== null)) {
        const current = s.fit_ranges_nm.EL.map(nmToX).sort((a,b)=>a-b);
        const newX = [xs.elLo ?? current[0], xs.elHi ?? current[1]];
        s.fit_ranges_nm.EL = clampRangeNm('EL', newX.map(xToNm));
        changed = true;
      }
      if (changed) {
        state.settings = s;
        renderControls();
        updateServer(false).then(() => renderPlot()).catch(err => setMessage(err.message, true));
      }
    }

    function readShapeX(ev, idx) {
      const a = ev[`shapes[${idx}].x0`];
      const b = ev[`shapes[${idx}].x1`];
      if (a === undefined && b === undefined) return null;
      const nums = [a, b].filter(v => v !== undefined).map(parseFloat).filter(Number.isFinite);
      return nums.length ? nums.reduce((x,y)=>x+y,0) / nums.length : null;
    }

    document.addEventListener('click', async (event) => {
      const segButton = event.target.closest('.seg button');
      if (segButton) {
        const group = segButton.closest('.seg');
        const next = readSettingsFromDom();
        next[group.dataset.key] = segButton.dataset.value;
        await updateSettings(next, true);
      }
    });

    for (const id of ['EQE_min','EQE_max','EL_min','EL_max','temperature_K','residual','max_nfev']) {
      document.addEventListener('change', async (event) => {
        if (event.target.id === id) await updateServer(true);
      });
    }

    async function uploadCsv(kind, file) {
      if (!file) return;
      const content = await file.text();
      setMessage(`Uploading ${kind}...`);
      state = await api('/api/upload', {kind, filename: file.name, content});
      renderAll();
    }

    function setupDropzone(kind) {
      const drop = $(`${kind}_drop`);
      const input = $(`${kind}_file`);
      drop.addEventListener('click', () => input.click());
      for (const eventName of ['dragenter', 'dragover']) {
        drop.addEventListener(eventName, (event) => {
          event.preventDefault();
          drop.classList.add('dragover');
        });
      }
      for (const eventName of ['dragleave', 'drop']) {
        drop.addEventListener(eventName, (event) => {
          event.preventDefault();
          drop.classList.remove('dragover');
        });
      }
      drop.addEventListener('drop', async (event) => {
        try { await uploadCsv(kind, event.dataTransfer.files[0]); }
        catch (err) { setMessage(err.message, true); }
      });
    }

    setupDropzone('EQE');
    setupDropzone('EL');

    $('EQE_file').addEventListener('change', async (event) => {
      try { await uploadCsv('EQE', event.target.files[0]); }
      catch (err) { setMessage(err.message, true); }
      event.target.value = '';
    });

    $('EL_file').addEventListener('change', async (event) => {
      try { await uploadCsv('EL', event.target.files[0]); }
      catch (err) { setMessage(err.message, true); }
      event.target.value = '';
    });

    $('fit').onclick = async () => {
      try {
        setMessage('Fitting...');
        state = await api('/api/fit', {settings: readSettingsFromDom()});
        renderAll();
      } catch (err) { setMessage(err.message, true); }
    };
    $('save').onclick = async () => {
      try {
        state = await api('/api/save', {
          settings: readSettingsFromDom(),
          filename_prefix: $('filename_prefix').value.trim()
        });
        renderAll();
      } catch (err) { setMessage(err.message, true); }
    };
    $('refresh').onclick = load;

    load().catch(err => setMessage(err.message, true));
  </script>
</body>
</html>
"""


def main() -> None:
    atexit.register(clear_uploaded_spectra)
    clear_uploaded_spectra()
    parser = argparse.ArgumentParser(description="Run the draggable Marcus CT fitting WebUI.")
    parser.add_argument("--host", default=os.environ.get("HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8502")))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    port = args.port
    host = args.host
    server = ThreadingHTTPServer((host, port), Handler)
    browser_host = "localhost" if host in ("0.0.0.0", "::") else host
    url = f"http://{browser_host}:{port}"
    print(f"Marcus CT draggable WebUI running at http://{host}:{port}")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    finally:
        server.server_close()
        clear_uploaded_spectra()


if __name__ == "__main__":
    main()
