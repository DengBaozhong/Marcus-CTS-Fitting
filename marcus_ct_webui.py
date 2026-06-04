from __future__ import annotations

import argparse
import atexit
import os
import webbrowser
from http.server import ThreadingHTTPServer

from marcus_ct.server import Handler
from marcus_ct.spectra import clear_uploaded_spectra


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
