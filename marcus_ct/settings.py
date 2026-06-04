from __future__ import annotations

import json

import numpy as np

from .config import DEFAULT_SETTINGS, SETTINGS_PATH


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


