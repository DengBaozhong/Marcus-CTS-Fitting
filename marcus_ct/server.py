from __future__ import annotations

import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote, urlparse

from .config import FRONTEND_DIR, INDEX_HTML_PATH, PLOTLY_JS
from .export import csv_download_bytes
from .fitting import fit_ct
from .payload import state_payload
from .settings import load_settings, migrate_settings, sanitize_settings, save_settings
from .spectra import read_spectrum, read_spectrum_optional, require_ready_for_mode, save_uploaded_csv, safe_filename_prefix


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
            self.send_text(INDEX_HTML_PATH.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        elif path == "/plotly.min.js":
            wrapped = (
                b"var module=undefined;var exports=undefined;\n"
                + PLOTLY_JS.read_bytes()
                + b"\nwindow.Plotly=window.Plotly||window.moduleName;\n"
            )
            self.send_bytes(wrapped, "application/javascript")
        elif path in ("/style.css", "/app.js"):
            self.send_frontend_asset(path)
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
                filename, body = csv_download_bytes(APP_STATE.settings, payload.get("filename_prefix", ""))
                self.send_download(filename, body)
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

    def send_frontend_asset(self, path: str) -> None:
        asset = FRONTEND_DIR / path.lstrip("/")
        if not asset.exists():
            self.send_error(404)
            return
        self.send_bytes(asset.read_bytes(), mimetypes.guess_type(str(asset))[0])

    def send_download(self, filename: str, body: bytes) -> None:
        safe_name = safe_filename_prefix(Path(filename).stem) + ".csv"
        ascii_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", safe_name).strip("._-") or "marcus_ct_fit.csv"
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(safe_name)}')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
