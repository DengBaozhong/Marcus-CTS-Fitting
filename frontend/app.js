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

    function filenameFromDisposition(disposition) {
      const text = String(disposition || '');
      const utf8 = text.match(/filename\\*=UTF-8''([^;]+)/i);
      if (utf8) {
        try { return decodeURIComponent(utf8[1].replace(/"/g, '').trim()); }
        catch (err) { return utf8[1].replace(/"/g, '').trim(); }
      }
      const ascii = text.match(/filename="?([^";]+)"?/i);
      return ascii ? ascii[1].trim() : 'marcus_ct_fit.csv';
    }

    async function saveBlobToUser(blob, filename) {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }

    function downloadFilenameSuggestion() {
      const prefix = $('filename_prefix').value.trim() || 'marcus_ct_fit';
      const clean = prefix.replace(/[^\w.\-]+/g, '_').replace(/^[._-]+|[._-]+$/g, '') || 'marcus_ct_fit';
      const now = new Date();
      const pad = (n) => String(n).padStart(2, '0');
      const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
      return `${clean}_${stamp}.csv`;
    }

    async function downloadCsv() {
      let fileHandle = null;
      if (window.showSaveFilePicker) {
        fileHandle = await window.showSaveFilePicker({
          suggestedName: downloadFilenameSuggestion(),
          types: [{description: 'CSV file', accept: {'text/csv': ['.csv']}}],
        });
      }
      const response = await fetch('/api/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Accept': 'text/csv'},
        body: JSON.stringify({
          settings: readSettingsFromDom(),
          filename_prefix: $('filename_prefix').value.trim()
        }),
      });
      if (!response.ok) {
        let message = response.statusText || 'Save failed';
        try {
          const data = await response.json();
          message = data.error || message;
        } catch (err) {
          const text = await response.text();
          if (text) message = text;
        }
        throw new Error(message);
      }
      const filename = filenameFromDisposition(response.headers.get('Content-Disposition'));
      const blob = await response.blob();
      if (fileHandle) {
        const writable = await fileHandle.createWritable();
        await writable.write(blob);
        await writable.close();
      } else {
        await saveBlobToUser(blob, filename);
      }
      state = await api('/api/state');
      renderAll();
      setMessage(`Saved to your computer: ${filename}`);
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
      $('EQE_unload').hidden = !eqeLoaded;
      $('EL_unload').hidden = !elLoaded;
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

    async function unloadCsv(kind) {
      setMessage(`Unloading ${kind}...`);
      state = await api('/api/unload', {kind});
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

    $('EQE_unload').addEventListener('click', async () => {
      try { await unloadCsv('EQE'); }
      catch (err) { setMessage(err.message, true); }
    });

    $('EL_unload').addEventListener('click', async () => {
      try { await unloadCsv('EL'); }
      catch (err) { setMessage(err.message, true); }
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
        await downloadCsv();
      } catch (err) { setMessage(err.message, true); }
    };
    $('refresh').onclick = load;

    load().catch(err => setMessage(err.message, true));
