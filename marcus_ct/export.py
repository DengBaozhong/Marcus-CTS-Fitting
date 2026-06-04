from __future__ import annotations

from datetime import datetime
from io import StringIO

import numpy as np
import pandas as pd

from .model import add_predictions, build_fit_curves
from .spectra import read_spectrum, read_spectrum_optional, require_ready_for_mode, safe_filename_prefix


def padded_series(values: np.ndarray | pd.Series | list[float], length: int) -> pd.Series:
    series = pd.Series(np.asarray(values, dtype=float))
    if len(series) < length:
        series = series.reindex(range(length))
    return series.reset_index(drop=True)

def build_result_dataframe(settings: dict) -> pd.DataFrame:
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
    return out

def result_filename(filename_prefix: str = "") -> str:
    prefix = safe_filename_prefix(filename_prefix)
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

def csv_download_bytes(settings: dict, filename_prefix: str = "") -> tuple[str, bytes]:
    out = build_result_dataframe(settings)
    buffer = StringIO()
    out.to_csv(buffer, index=False)
    return result_filename(filename_prefix), ("\ufeff" + buffer.getvalue()).encode("utf-8")


