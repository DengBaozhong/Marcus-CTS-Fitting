from __future__ import annotations

from pathlib import Path

import plotly


HC_EV_NM = 1239.841984
KB_EV_K = 8.617333262145e-5
APP_DIR = Path(__file__).resolve().parent.parent
SETTINGS_PATH = APP_DIR / "marcus_ct_settings.json"
UPLOADS_DIR = APP_DIR / "uploaded_spectra"
FRONTEND_DIR = APP_DIR / "frontend"
INDEX_HTML_PATH = FRONTEND_DIR / "index.html"
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
