# Marcus CT WebUI

A browser-based tool for fitting EQE and electroluminescence spectra with Marcus charge-transfer theory.

## Local Run

```powershell
python -m pip install -r requirements.txt
python marcus_ct_webui.py
```

Open:

```text
http://localhost:8502
```

## Deploy As A Persistent Web App

GitHub Pages cannot run this app because the fitting uses a Python backend with `scipy`.
Use a Python web-hosting service such as Render, Railway, Fly.io, or Hugging Face Spaces.

### Render

1. Push this folder to a GitHub repository.
2. In Render, create a new Web Service from that repository.
3. Use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `python marcus_ct_webui.py --host 0.0.0.0 --no-browser`
4. Render will provide a public URL after deployment.

The included `render.yaml` can also be used as a Render Blueprint.

## Portable Windows Folder

To build a portable Windows package with its own Python runtime:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_portable_webui.ps1
```

Then distribute the generated `dist\MarcusCT_WebUI_Portable` folder.
