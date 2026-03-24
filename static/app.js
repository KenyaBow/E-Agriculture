
(() => {
  const state = { installPrompt: null };

  const $ = (id) => document.getElementById(id);
  const page = document.body.dataset.page || 'home';
  const toastRoot = $('toast-root');

  function toast(message, kind = 'info') {
    if (!toastRoot) return;
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.textContent = message;
    toastRoot.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function fmtDate(d) {
    const dt = new Date(d);
    return dt.toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });
  }

  function todayISO() {
    const d = new Date();
    const offset = d.getTimezoneOffset() * 60000;
    return new Date(d.getTime() - offset).toISOString().slice(0, 10);
  }

  function safeText(value) {
    if (value === null || value === undefined || value === '') return '—';
    if (Array.isArray(value)) return value.join(', ');
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  async function api(url, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const key = `fp-cache:${url}:${method}`;
    try {
      const res = await fetch(url, options);
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(text || `Request failed (${res.status})`);
      }
      const data = await res.json();
      if (method === 'GET') {
        localStorage.setItem(key, JSON.stringify(data));
      }
      return data;
    } catch (err) {
      if (method === 'GET') {
        const cached = localStorage.getItem(key);
        if (cached) {
          toast('Using cached data because the live request failed.', 'info');
          return JSON.parse(cached);
        }
      }
      throw err;
    }
  }

  function renderResult(target, title, html) {
    if (!target) return;
    target.innerHTML = `<h3>${title}</h3>${html}`;
  }

  function renderAnalysis(data) {
    const issues = (data.issues || []).map((x) => `<li>${x}</li>`).join('');
    const actions = (data.actions || []).map((x) => `<li>${x}</li>`).join('');
    return `
      <div class="kpi">
        <div><strong>Status</strong><div>${safeText(data.status)}</div></div>
        <div><strong>Score</strong><div>${safeText(data.score)}</div></div>
        <div><strong>Detected</strong><div>${safeText(data.detected_plant || data.texture_hint || data.soil_moisture_hint)}</div></div>
        <div><strong>Confidence</strong><div>${safeText(data.detection_confidence || data.texture_hint)}</div></div>
      </div>
      ${data.crop_note ? `<p>${data.crop_note}</p>` : ''}
      ${data.combined_note ? `<p>${data.combined_note}</p>` : ''}
      ${data.fertilizer ? `<p><strong>Fertilizer:</strong> ${data.fertilizer}</p>` : ''}
      <p><strong>Resolution:</strong> ${safeText(data.resolution || data.market_message || data.summary)}</p>
      <h4>Issues</h4>
      <ul>${issues}</ul>
      <h4>Actions</h4>
      <ul>${actions}</ul>
    `;
  }

  function showWeather(data) {
    const summary = $('weather-summary');
    const days = $('weather-days');
    const detail = $('weather-detail');
    const meta = $('weather-meta');
    if (!summary || !days || !detail || !meta) return;

    meta.textContent = `${data.place} · ${data.mode} · ${data.source}`;
    summary.innerHTML = `
      <div class="kpi">
        <div><strong>Selected date</strong><div>${fmtDate(data.target_date)}</div></div>
        <div><strong>Weather note</strong><div>${safeText(data.note)}</div></div>
        <div><strong>Latitude</strong><div>${safeText(data.lat)}</div></div>
        <div><strong>Longitude</strong><div>${safeText(data.lon)}</div></div>
      </div>
    `;

    const series = data.series || [];
    days.innerHTML = series.map((row, idx) => `
      <div class="day-card ${row.date === data.target_date ? 'active' : ''}" data-idx="${idx}">
        <strong>${row.date}</strong>
        <small>${safeText(row.summary)}</small>
        <small>Max ${safeText(row.temperature_2m_max)}°C · Min ${safeText(row.temperature_2m_min)}°C</small>
      </div>
    `).join('');

    function fillDetail(row) {
      if (!row) return;
      detail.innerHTML = `
        <h4>${row.date}</h4>
        <p>${safeText(row.summary)}</p>
        <div class="kpi">
          <div><strong>Max temp</strong><div>${safeText(row.temperature_2m_max)}°C</div></div>
          <div><strong>Min temp</strong><div>${safeText(row.temperature_2m_min)}°C</div></div>
          <div><strong>Rain</strong><div>${safeText(row.rain_sum)} mm</div></div>
          <div><strong>Wind</strong><div>${safeText(row.windspeed_10m_max)} km/h</div></div>
          <div><strong>Solar</strong><div>${safeText(row.shortwave_radiation_sum)}</div></div>
          <div><strong>ET0</strong><div>${safeText(row.reference_evapotranspiration)}</div></div>
        </div>
        <h4>Advice</h4>
        <ul>${(row.advice || []).map((x) => `<li>${x}</li>`).join('')}</ul>
      `;
    }

    const current = series.find((row) => row.date === data.target_date) || series[Math.floor(series.length / 2)];
    fillDetail(current);

    days.querySelectorAll('.day-card').forEach((card) => {
      card.addEventListener('click', () => {
        days.querySelectorAll('.day-card').forEach((n) => n.classList.remove('active'));
        card.classList.add('active');
        fillDetail(series[Number(card.dataset.idx)]);
      });
    });
  }

  function initWeather() {
    const place = $('weather-place');
    const date = $('weather-date');
    const search = $('weather-search');
    const todayBtn = $('weather-today');
    if (!place || !date || !search) return;
    date.value = todayISO();

    async function run() {
      const url = `/api/weather?place=${encodeURIComponent(place.value)}&date=${encodeURIComponent(date.value)}`;
      $('weather-days').innerHTML = '<div class="placeholder">Loading weather...</div>';
      $('weather-detail').innerHTML = '';
      try {
        const data = await api(url);
        showWeather(data);
        toast('Weather loaded.', 'good');
      } catch (err) {
        $('weather-days').innerHTML = '';
        $('weather-detail').innerHTML = `<p class="placeholder">${err.message}</p>`;
        toast(err.message, 'bad');
      }
    }
    search.addEventListener('click', run);
    todayBtn?.addEventListener('click', () => { date.value = todayISO(); run(); });
    run();
  }

  function initPlant() {
    const button = $('plant-analyze');
    const result = $('plant-result');
    if (!button || !result) return;
    button.addEventListener('click', async () => {
      const file = $('plant-image')?.files?.[0];
      if (!file) return toast('Choose a leaf photo first.', 'bad');
      const form = new FormData();
      form.append('image', file);
      form.append('plant_name', $('plant-name')?.value || '');
      renderResult(result, 'Working', '<p>Analyzing leaf image...</p>');
      try {
        const data = await api('/api/plant/analyze', { method: 'POST', body: form });
        renderResult(result, `Leaf analysis · ${safeText(data.status)}`, renderAnalysis(data));
        toast(data.healthy ? 'Leaf looks healthy.' : 'Leaf needs attention.', data.healthy ? 'good' : 'bad');
        notifyFarm(`Plant analysis complete`, data.healthy ? 'The leaf looks healthy.' : 'The leaf needs attention.');
      } catch (err) {
        renderResult(result, 'Error', `<p>${err.message}</p>`);
        toast(err.message, 'bad');
      }
    });
  }

  function initSoil() {
    const button = $('soil-analyze');
    const result = $('soil-result');
    if (!button || !result) return;
    button.addEventListener('click', async () => {
      const soil = $('soil-image')?.files?.[0];
      if (!soil) return toast('Choose a soil photo first.', 'bad');
      const form = new FormData();
      form.append('soil_image', soil);
      form.append('crop', $('soil-crop')?.value || '');
      form.append('location', $('soil-location')?.value || '');
      const leaf = $('soil-leaf-image')?.files?.[0];
      if (leaf) form.append('leaf_image', leaf);
      renderResult(result, 'Working', '<p>Analyzing soil and leaf data...</p>');
      try {
        const data = await api('/api/soil/analyze', { method: 'POST', body: form });
        renderResult(result, 'Soil analysis', renderAnalysis(data));
      } catch (err) {
        renderResult(result, 'Error', `<p>${err.message}</p>`);
        toast(err.message, 'bad');
      }
    });
  }

  function initChat() {
    const box = $('chatbox');
    const input = $('chat-input');
    const send = $('chat-send');
    if (!box || !input || !send) return;
    const append = (text, who) => {
      const d = document.createElement('div');
      d.className = `bubble ${who}`;
      d.textContent = text;
      box.appendChild(d);
      box.scrollTop = box.scrollHeight;
      return d;
    };
    append('Hello. Ask me about weather, plants, soil, irrigation, diseases, reports, or market timing.', 'bot');
    async function sendMsg() {
      const text = input.value.trim();
      if (!text) return;
      append(text, 'user');
      input.value = '';
      const thinking = append('Thinking...', 'bot');
      try {
        const data = await api('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text })
        });
        thinking.textContent = data.reply || 'No response.';
      } catch (err) {
        thinking.textContent = err.message;
      }
    }
    send.addEventListener('click', sendMsg);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendMsg(); });
  }

  async function initReport() {
    const list = $('report-list');
    const refresh = $('refresh-report');
    if (!list) return;
    async function load() {
      list.innerHTML = '<p class="placeholder">Loading report...</p>';
      try {
        const data = await api('/api/report/latest');
        const records = data.records || [];
        if (!records.length) {
          list.innerHTML = '<p class="placeholder">No saved records yet.</p>';
          return;
        }
        list.innerHTML = records.slice().reverse().map((r) => `
          <div class="summary-box" style="margin-bottom:12px">
            <strong>${safeText(r.kind).toUpperCase()}</strong>
            <div class="meta-line">${safeText(r.timestamp)}</div>
            <pre style="white-space:pre-wrap;overflow:auto;margin:10px 0 0;font-family:inherit;font-size:.95rem;line-height:1.4">${JSON.stringify(r.payload, null, 2)}</pre>
          </div>
        `).join('');
      } catch (err) {
        list.innerHTML = `<p class="placeholder">${err.message}</p>`;
      }
    }
    refresh?.addEventListener('click', load);
    load();
  }

  function initRecommendation() {
    const button = $('rec-run');
    const result = $('rec-result');
    if (!button || !result) return;
    button.addEventListener('click', async () => {
      renderResult(result, 'Working', '<p>Building crop recommendations...</p>');
      try {
        const data = await api('/api/recommendations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            goal: $('rec-goal')?.value || '',
            condition: $('rec-condition')?.value || '',
            water: $('rec-water')?.value || '',
            market_access: $('rec-market')?.value || '',
          })
        });
        const items = (data.recommendations || []).map((x) => `
          <div class="summary-box" style="margin-top:10px">
            <strong>${safeText(x.crop).toUpperCase()}</strong>
            <p>${safeText(x.reason)}</p>
            <p class="meta-line">Harvest: ${safeText(x.days_to_harvest)} days · Market: ${safeText(x.market)}</p>
          </div>
        `).join('');
        renderResult(result, 'Recommended crops', `<p>${safeText(data.summary)}</p>${items}`);
      } catch (err) {
        renderResult(result, 'Error', `<p>${err.message}</p>`);
      }
    });
  }

  function initDisease() {
    const button = $('disease-run');
    const result = $('disease-result');
    if (!button || !result) return;
    button.addEventListener('click', async () => {
      renderResult(result, 'Working', '<p>Checking regional disease risk...</p>');
      try {
        const params = new URLSearchParams({ area: $('disease-area')?.value || '', crop: $('disease-crop')?.value || '' });
        const data = await api(`/api/diseases?${params.toString()}`);
        renderResult(result, `Disease risk · ${safeText(data.region)}`, `
          <p><strong>Common diseases:</strong> ${safeText(data.common_diseases)}</p>
          <h4>Prevention</h4>
          <ul>${(data.prevention || []).map((x) => `<li>${x}</li>`).join('')}</ul>
        `);
      } catch (err) {
        renderResult(result, 'Error', `<p>${err.message}</p>`);
      }
    });
  }

  function initIrrigation() {
    const button = $('irr-run');
    const result = $('irr-result');
    if (!button || !result) return;
    if ($('irr-date')) $('irr-date').value = todayISO();
    button.addEventListener('click', async () => {
      renderResult(result, 'Working', '<p>Building irrigation plan...</p>');
      try {
        const data = await api('/api/irrigation', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            crop: $('irr-crop')?.value || '',
            planting_date: $('irr-date')?.value || todayISO(),
            location: $('irr-location')?.value || '',
            soil: $('irr-soil')?.value || '',
          })
        });
        renderResult(result, 'Irrigation plan', `
          <div class="kpi">
            <div><strong>Interval</strong><div>${safeText(data.watering_interval_days)} days</div></div>
            <div><strong>Planting date</strong><div>${safeText(data.planting_date)}</div></div>
            <div><strong>Location</strong><div>${safeText(data.location)}</div></div>
            <div><strong>Soil</strong><div>${safeText(data.soil)}</div></div>
          </div>
          <p><strong>Water tip:</strong> ${safeText(data.water_tip)}</p>
          <h4>Plan</h4>
          <ul>${(data.plan || []).map((x) => `<li>${x}</li>`).join('')}</ul>
          <p class="meta-line">Weather context: ${safeText(data.weather_context?.summary)}</p>
        `);
      } catch (err) {
        renderResult(result, 'Error', `<p>${err.message}</p>`);
      }
    });
  }

  function initMarket() {
    const button = $('market-run');
    const result = $('market-result');
    if (!button || !result) return;
    if ($('market-date')) $('market-date').value = todayISO();
    if ($('market-target')) $('market-target').value = todayISO();
    button.addEventListener('click', async () => {
      renderResult(result, 'Working', '<p>Checking harvest timing and market pressure...</p>');
      try {
        const data = await api('/api/market', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            crop: $('market-crop')?.value || 'maize',
            planting_date: $('market-date')?.value || todayISO(),
            location: $('market-location')?.value || '',
            target_date: $('market-target')?.value || todayISO(),
          })
        });
        renderResult(result, 'Market plan', `
          <div class="kpi">
            <div><strong>Market score</strong><div>${safeText(data.market_score)}</div></div>
            <div><strong>Harvest date</strong><div>${safeText(data.estimated_harvest_date)}</div></div>
            <div><strong>Target date</strong><div>${safeText(data.target_date)}</div></div>
            <div><strong>Risk</strong><div>${safeText(data.market_message)}</div></div>
          </div>
          <p><strong>Seasonal risk:</strong> ${data.seasonal_glut_risk ? 'High' : 'Lower'}</p>
          <h4>Advice</h4>
          <ul>${(data.advice || []).map((x) => `<li>${x}</li>`).join('')}</ul>
        `);
      } catch (err) {
        renderResult(result, 'Error', `<p>${err.message}</p>`);
      }
    });
  }

  async function notifyFarm(title, body) {
    if (!('Notification' in window)) return;
    try {
      if (Notification.permission === 'default') {
        await Notification.requestPermission();
      }
      if (Notification.permission === 'granted') {
        new Notification(title, { body });
      }
    } catch (_) {}
  }

  function installPrompt() {
    const btn = $('installBtn');
    if (!btn) return;
    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      state.installPrompt = e;
      btn.hidden = false;
    });
    btn.addEventListener('click', async () => {
      if (!state.installPrompt) return;
      state.installPrompt.prompt();
      await state.installPrompt.userChoice.catch(() => {});
      btn.hidden = true;
      state.installPrompt = null;
    });
  }

  function lockPortrait() {
    try {
      if (screen.orientation && screen.orientation.lock) {
        // Some browsers only allow this inside installed PWAs or after a gesture.
        screen.orientation.lock('portrait').catch(() => {});
      }
    } catch (_) {}
  }

  function registerSW() {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/service-worker.js').catch(() => {});
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    registerSW();
    installPrompt();
    lockPortrait();

    initWeather();
    initPlant();
    initSoil();
    initChat();
    initReport();
    initRecommendation();
    initDisease();
    initIrrigation();
    initMarket();
  });
})();
