from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .config import APP_DIR, HC_EV_NM, UPLOADS_DIR


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


