const INTENSITY_COLORS = {
  wu: '#64b5f6', cd: '#64b5f6',
  active: '#ef5350', lt: '#ff7043', tempo: '#ffa726',
  recover: '#81c784', rest: '#81c784',
  map: '#ab47bc', ac: '#e91e63', nm: '#f44336', ftp: '#ff5722',
};

const TYPE_META = {
  wu:      { label: 'Warm Up' },
  active:  { label: 'Run' },
  recover: { label: 'Recovery' },
  cd:      { label: 'Cool Down' },
};

// Single source of truth for interval defaults (incl. fallbacks for plans
// missing a value) — don't hardcode copies of these elsewhere.
// speedMs is meters/second: 1609.344 / (pace in seconds per mile).
// e.g. 15:00 min/mile → 1609.344 / 900 ≈ 1.7882 (don't round further:
// 1.79 displays as 14:59).
const DEFS = {
  warmup:   { type: 'wu',      lengthType: 'time', durationSecs: 600, distanceM: 1000, speedMs: 1.7882, gradePct: 1 },
  run:      { type: 'active',  lengthType: 'time', durationSecs: 120, distanceM: 400,  speedMs: 3.5, gradePct: 1 },
  walk:     { type: 'recover', lengthType: 'time', durationSecs: 60,  distanceM: 200,  speedMs: 3.35, gradePct: 1 },
  cooldown: { type: 'cd',      lengthType: 'time', durationSecs: 600, distanceM: 500,  speedMs: 2.555, gradePct: 1 },
};

// ── State ─────────────────────────────────────────────────────────────────────

let state = { name: 'My Running Workout', intervals: [] };
let nextId = 1;
const nid = () => nextId++;

// ── Drag-to-reorder ───────────────────────────────────────────────────────────

let dragId = null;
let dragParentId = null;

function handleDragStart(e, id, parentId) {
  dragId = id;
  dragParentId = parentId;
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', String(id));
}

function handleDragOver(e, id, parentId) {
  e.stopPropagation();
  if (dragId === null || dragParentId !== parentId || dragId === id) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  document.querySelectorAll('.iv-drag-over').forEach(el => el.classList.remove('iv-drag-over'));
  const el = document.querySelector(`[data-id="${id}"]`);
  if (el) el.classList.add('iv-drag-over');
}

function handleDrop(e, id, parentId) {
  e.preventDefault();
  e.stopPropagation();
  document.querySelectorAll('.iv-drag-over').forEach(el => el.classList.remove('iv-drag-over'));
  if (dragId === null || dragParentId !== parentId || dragId === id) { dragId = null; return; }
  const list = parentId !== null
    ? state.intervals.find(iv => iv.id === parentId)?.children
    : state.intervals;
  if (!list) return;
  const fromIdx = list.findIndex(iv => iv.id === dragId);
  const toIdx   = list.findIndex(iv => iv.id === id);
  if (fromIdx === -1 || toIdx === -1) return;
  const [item] = list.splice(fromIdx, 1);
  list.splice(fromIdx < toIdx ? toIdx - 1 : toIdx, 0, item);
  dragId = null;
  render();
}

function handleDragEnd() {
  dragId = null;
  dragParentId = null;
  document.querySelectorAll('.iv-drag-over').forEach(el => el.classList.remove('iv-drag-over'));
}

const validationBar = document.getElementById('validation-bar');

// ── Duration helpers ──────────────────────────────────────────────────────────

function parseDuration(val) {
  const m = val.trim().match(/^(\d{1,3}):(\d{2})$/);
  if (m) return parseInt(m[1]) * 60 + parseInt(m[2]);
  const n = parseInt(val);
  return isNaN(n) || n <= 0 ? 0 : n * 60;
}

function fmtDuration(secs) {
  const m = Math.floor(secs / 60), s = secs % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

// ── Pace helpers ──────────────────────────────────────────────────────────────

function paceToMs(val) {
  const m = val.trim().match(/^(\d{1,3}):(\d{2})$/);
  if (!m) return 0;
  const secs = parseInt(m[1]) * 60 + parseInt(m[2]);
  return secs > 0 ? 1609.344 / secs : 0;
}

function msToPace(ms) {
  if (!ms) return '';
  const totalSecs = Math.round(1609.344 / ms);
  const m = Math.floor(totalSecs / 60), s = totalSecs % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

// ── Build plan from state ─────────────────────────────────────────────────────

function buildPlan() {
  function buildIv(iv) {
    if (iv.type === 'repeat') {
      return {
        name: 'Intervals',
        exit_trigger_type: 'repeat',
        exit_trigger_value: iv.repeats,
        intervals: iv.children.map(buildIv),
      };
    }
    const obj = {
      name: TYPE_META[iv.type]?.label || iv.type,
      exit_trigger_type: iv.lengthType === 'distance' ? 'distance' : 'time',
      exit_trigger_value: iv.lengthType === 'distance' ? iv.distanceM : iv.durationSecs,
      intensity_type: iv.type,
      targets: [{ type: 'speed', low: iv.speedMs, high: iv.speedMs }],
    };
    const controls = [];
    if (iv.gradePct !== 0) controls.push({ type: 'grade', value: +(iv.gradePct / 100).toFixed(4) });
    if (controls.length) obj.controls = controls;
    return obj;
  }

  return {
    header: { name: state.name },
    intervals: state.intervals.map(buildIv),
  };
}

// ── Render ────────────────────────────────────────────────────────────────────

function typeSelect(ivId, pid, currentType) {
  const opts = Object.entries(TYPE_META).map(([v, { label }]) =>
    `<option value="${v}"${currentType === v ? ' selected' : ''}>${label}</option>`
  ).join('');
  return `<select class="iv-type" onchange="updateField(${ivId},${pid},'type',this.value)">${opts}</select>`;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function renderInterval(iv, parentId = null) {
  const pid = parentId === null ? 'null' : parentId;

  if (iv.type === 'repeat') {
    const children = iv.children.map(c => renderInterval(c, iv.id)).join('');
    return `<div class="iv-repeat" data-id="${iv.id}"
      ondragover="handleDragOver(event,${iv.id},null)"
      ondrop="handleDrop(event,${iv.id},null)">
      <div class="iv-repeat-hdr">
        <span class="iv-drag" draggable="true"
          ondragstart="handleDragStart(event,${iv.id},null)"
          ondragend="handleDragEnd()">⠿</span>
        <span class="iv-badge">Repeat</span>
        <input type="number" class="iv-repeats" value="${iv.repeats}" min="1" max="99"
          onchange="updateField(${iv.id},null,'repeats',+this.value)">
        <span class="iv-x">×</span>
        <button class="iv-del" onclick="removeIv(${iv.id},null)">×</button>
      </div>
      <div class="iv-children">${children}</div>
    </div>`;
  }

  const isDist = iv.lengthType === 'distance';
  const lenCell = `<div class="iv-len-cell">
    <select class="iv-len-type" onchange="updateLenType(${iv.id},${pid},this.value)">
      <option value="time"${!isDist ? ' selected' : ''}>min</option>
      <option value="distance"${isDist ? ' selected' : ''}>m</option>
    </select>
    ${isDist
      ? `<input type="number" class="iv-len-val" value="${iv.distanceM}" min="1" step="10" onchange="updateField(${iv.id},${pid},'distanceM',+this.value)">`
      : `<input type="text" class="iv-len-val" value="${fmtDuration(iv.durationSecs)}" onchange="updateDur(${iv.id},${pid},this.value)">`
    }
  </div>`;

  return `<div class="iv-row" data-id="${iv.id}"
    ondragover="handleDragOver(event,${iv.id},${pid})"
    ondrop="handleDrop(event,${iv.id},${pid})">
    <span class="iv-drag" draggable="true"
      ondragstart="handleDragStart(event,${iv.id},${pid})"
      ondragend="handleDragEnd()">⠿</span>
    ${typeSelect(iv.id, pid, iv.type)}
    ${lenCell}
    <input type="text" class="iv-speed" value="${msToPace(iv.speedMs)}"
      onchange="updatePace(${iv.id},${pid},this.value)">
    <input type="number" class="iv-grade" value="${iv.gradePct}" step="0.5"
      onchange="updateField(${iv.id},${pid},'gradePct',+this.value)">
    <button class="iv-del" onclick="removeIv(${iv.id},${pid})">×</button>
  </div>`;
}

function render() {
  const el = document.getElementById('intervals-list');
  el.innerHTML = state.intervals.length
    ? state.intervals.map(iv => renderInterval(iv)).join('')
    : '<div class="iv-empty">Use the templates to add intervals.</div>';
  syncPreview();
}

// ── State mutations ───────────────────────────────────────────────────────────

function findIv(id, parentId) {
  if (parentId !== null) {
    const p = state.intervals.find(iv => iv.id === parentId);
    return p ? p.children.find(c => c.id === id) : null;
  }
  return state.intervals.find(iv => iv.id === id) || null;
}

function updateField(id, parentId, field, value) {
  const iv = findIv(id, parentId);
  if (iv) { iv[field] = value; syncPreview(); }
}

function updateDur(id, parentId, val) {
  const secs = parseDuration(val);
  if (secs > 0) updateField(id, parentId, 'durationSecs', secs);
}

function updateLenType(id, parentId, val) {
  const iv = findIv(id, parentId);
  if (iv) { iv.lengthType = val; render(); }
}

function updatePace(id, parentId, val) {
  const ms = paceToMs(val);
  if (ms > 0) updateField(id, parentId, 'speedMs', ms);
}

function removeIv(id, parentId) {
  if (parentId !== null) {
    const p = state.intervals.find(iv => iv.id === parentId);
    if (p) p.children = p.children.filter(c => c.id !== id);
  } else {
    state.intervals = state.intervals.filter(iv => iv.id !== id);
  }
  render();
}

// ── Template insertion ────────────────────────────────────────────────────────

function insertTemplate(name) {
  const g = 1;

  if (name === 'scaffold') {
    state = { name: 'My Running Workout', intervals: [] };
    nextId = 1;
    document.getElementById('workout-name').value = state.name;
    render();
    return;
  }

  if (name === 'repeat') {
    state.intervals.push({
      id: nid(), type: 'repeat', repeats: 4,
      children: [
        { id: nid(), ...DEFS.run,  gradePct: g },
        { id: nid(), ...DEFS.walk, gradePct: g },
      ],
    });
    render();
    return;
  }

  if (DEFS[name]) {
    state.intervals.push({ id: nid(), ...DEFS[name], gradePct: g });
    render();
  }
}

// ── Validate & preview ────────────────────────────────────────────────────────

let validateTimeout;

function syncPreview() {
  clearTimeout(validateTimeout);
  validateTimeout = setTimeout(validateAndPreview, 300);
}

document.getElementById('workout-name').addEventListener('input', e => {
  state.name = e.target.value;
  syncPreview();
});

async function validateAndPreview() {
  const plan = buildPlan();

  if (!state.intervals.length) {
    setValidation('', '');
    clearChart();
    return;
  }

  try {
    const resp = await fetch('/workouts/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(plan),
    });
    if (resp.ok) {
      setValidation('ok', '✓ Valid');
      drawChart();
    } else {
      const err = await resp.json();
      setValidation('err', formatValidationError(err.detail));
      clearChart();
    }
  } catch {
    setValidation('err', 'Cannot reach server');
  }
}

function setValidation(cls, msg) {
  validationBar.textContent = msg;
  validationBar.className = 'validation-bar' + (cls ? ' ' + cls : '') + (cls === 'ok' ? ' clickable' : '');
  if (cls !== 'ok') {
    document.getElementById('json-preview').style.display = 'none';
  }
}

function toggleJsonPreview() {
  if (!validationBar.classList.contains('ok')) return;
  const preview = document.getElementById('json-preview');
  if (preview.style.display === 'block') {
    preview.style.display = 'none';
  } else {
    document.getElementById('json-pre').textContent = JSON.stringify(buildPlan(), null, 2);
    preview.style.display = 'block';
  }
}

function formatValidationError(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(e => `${e.loc?.join('.')} — ${e.msg}`).join('; ');
  }
  return JSON.stringify(detail);
}

// ── Chart ─────────────────────────────────────────────────────────────────────

let chart;

function clearChart() {
  if (chart) { chart.destroy(); chart = null; }
}

function flattenIntervals(intervals) {
  const steps = [];
  for (const interval of (intervals || [])) {
    if (interval.exit_trigger_type === 'repeat') {
      const times = interval.exit_trigger_value || 0;
      for (let i = 0; i < times; i++) {
        steps.push(...flattenIntervals(interval.intervals));
      }
    } else {
      const speedTarget = interval.targets?.find(t => t.type === 'speed');
      const gradeControl = interval.controls?.find(c => c.type === 'grade');
      const spd = speedTarget ? (speedTarget.low + speedTarget.high) / 2 : DEFS.run.speedMs;
      const dur = interval.exit_trigger_type === 'distance'
        ? Math.round((interval.exit_trigger_value || DEFS.run.distanceM) / (spd || DEFS.run.speedMs))
        : (interval.exit_trigger_value || 60);
      steps.push({
        duration: dur,
        speed: spd,
        grade: gradeControl ? gradeControl.value * 100 : 0,
        intensity: interval.intensity_type || 'active',
      });
    }
  }
  return steps;
}

const segmentLinesPlugin = {
  id: 'segmentLines',
  afterDraw(chart) {
    const times = chart.options.plugins.segmentLines?.times;
    if (!times?.length) return;
    const { ctx, chartArea, scales } = chart;
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.13)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 4]);
    for (const t of times) {
      const x = scales.x.getPixelForValue(t);
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
    }
    ctx.restore();
  }
};

function msToMph(ms) { return +(ms * 2.237).toFixed(2); }
function formatTime(s) {
  const m = Math.floor(s / 60), sec = s % 60;
  return sec === 0 ? `${m}m` : `${m}:${String(sec).padStart(2, '0')}`;
}

function flattenStateIntervals(intervals) {
  const steps = [];
  for (const iv of (intervals || [])) {
    if (iv.type === 'repeat') {
      const times = iv.repeats || 0;
      for (let i = 0; i < times; i++) {
        for (const child of (iv.children || [])) {
          const spd = child.speedMs || DEFS.run.speedMs;
          const dur = child.lengthType === 'distance'
            ? Math.round((child.distanceM || DEFS.run.distanceM) / spd)
            : (child.durationSecs || 60);
          steps.push({ duration: dur, speed: spd, grade: child.gradePct || 0, ivId: child.id });
        }
      }
    } else {
      const spd = iv.speedMs || DEFS.run.speedMs;
      const dur = iv.lengthType === 'distance'
        ? Math.round((iv.distanceM || DEFS.run.distanceM) / spd)
        : (iv.durationSecs || 60);
      steps.push({ duration: dur, speed: spd, grade: iv.gradePct || 0, ivId: iv.id });
    }
  }
  return steps;
}

function drawChart() {
  const steps = flattenStateIntervals(state.intervals);
  if (!steps.length) { clearChart(); return; }

  const speedData = [], gradeData = [], dataIndexToIvId = [];
  const boundaryTimes = [];
  let t = 0;

  for (let si = 0; si < steps.length; si++) {
    const step = steps[si];
    if (si > 0) boundaryTimes.push(t);
    speedData.push({ x: t, y: msToMph(step.speed) });
    gradeData.push({ x: t, y: step.grade });
    dataIndexToIvId.push(step.ivId);
    speedData.push({ x: t + step.duration, y: msToMph(step.speed) });
    gradeData.push({ x: t + step.duration, y: step.grade });
    dataIndexToIvId.push(step.ivId);
    t += step.duration;
  }

  function highlightRow(ivId) {
    document.querySelectorAll('.iv-row.iv-highlight').forEach(el => el.classList.remove('iv-highlight'));
    if (ivId != null) {
      const row = document.querySelector(`.iv-row[data-id="${ivId}"]`);
      if (row) row.classList.add('iv-highlight');
    }
  }

  clearChart();
  chart = new Chart(document.getElementById('workout-chart').getContext('2d'), {
    type: 'line',
    plugins: [segmentLinesPlugin],
    data: {
      datasets: [
        {
          label: 'Speed (mph)',
          data: speedData,
          borderColor: '#ef5350',
          backgroundColor: 'rgba(239,83,80,0.12)',
          fill: true, stepped: true, tension: 0, pointRadius: 0,
          yAxisID: 'y',
        },
        {
          label: 'Grade (%)',
          data: gradeData,
          borderColor: '#64b5f6',
          backgroundColor: 'transparent',
          fill: false, stepped: true, tension: 0, pointRadius: 0,
          yAxisID: 'y1',
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: {
        legend: { labels: { color: '#71717a', boxWidth: 10, font: { size: 11 } } },
        segmentLines: { times: boundaryTimes },
      },
      onHover: (event, elements) => {
        highlightRow(elements.length ? dataIndexToIvId[elements[0].index] : null);
      },
      scales: {
        x: {
          type: 'linear',
          ticks: {
            color: '#a1a1aa', maxTicksLimit: 12, font: { size: 10 },
            callback: val => formatTime(Math.round(val)),
          },
          grid: { color: '#e8e8eb' },
        },
        y:  { ticks: { color: '#71717a', font: { size: 10 } }, grid: { color: '#e8e8eb' },
              title: { display: true, text: 'mph', color: '#a1a1aa', font: { size: 10 } } },
        y1: { position: 'right', ticks: { color: '#71717a', font: { size: 10 } }, grid: { drawOnChartArea: false },
              title: { display: true, text: 'grade %', color: '#a1a1aa', font: { size: 10 } } },
      },
    },
  });
}

// ── Load plan into editor ─────────────────────────────────────────────────────

function planToState(plan) {
  function ivToState(iv) {
    if (iv.exit_trigger_type === 'repeat') {
      return {
        id: nid(), type: 'repeat',
        repeats: iv.exit_trigger_value || 1,
        children: (iv.intervals || []).map(ivToState),
      };
    }
    const speedTarget = iv.targets?.find(t => t.type === 'speed');
    const gradeControl = iv.controls?.find(c => c.type === 'grade');
    const isDist = iv.exit_trigger_type === 'distance';
    return {
      id: nid(),
      type: iv.intensity_type || 'active',
      lengthType: isDist ? 'distance' : 'time',
      durationSecs: !isDist ? (iv.exit_trigger_value || 60) : 60,
      distanceM: isDist ? (iv.exit_trigger_value || DEFS.run.distanceM) : DEFS.run.distanceM,
      speedMs: speedTarget ? speedTarget.low : DEFS.run.speedMs,
      gradePct: gradeControl ? +(gradeControl.value * 100).toFixed(1) : 0,
    };
  }
  return {
    name: plan.header?.name || 'Workout',
    intervals: (plan.intervals || []).map(ivToState),
  };
}

let _historyRows = [];

function loadFromHistory(id) {
  const row = _historyRows.find(r => r.id === id);
  if (!row?.plan_json) return;
  const plan = typeof row.plan_json === 'string' ? JSON.parse(row.plan_json) : row.plan_json;
  nextId = 1;
  state = planToState(plan);
  document.getElementById('workout-name').value = state.name;
  render();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── Push ──────────────────────────────────────────────────────────────────────

async function pushWorkout() {
  if (!state.intervals.length) {
    document.getElementById('push-status').textContent = 'Add steps first';
    return;
  }
  const plan = buildPlan();
  const dateVal = document.getElementById('schedule-date').value;
  const scheduled_at = dateVal ? new Date(dateVal + 'T00:00:00').toISOString() : null;

  const btn = document.getElementById('push-btn');
  const statusEl = document.getElementById('push-status');
  btn.disabled = true;
  statusEl.style.color = '#71717a';
  statusEl.textContent = 'Pushing to Wahoo…';

  try {
    const resp = await fetch('/workouts/push', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan, scheduled_at }),
    });
    const data = await resp.json();
    if (resp.ok) {
      statusEl.style.color = '#4caf50';
      statusEl.textContent = `✓ Pushed — workout ID: ${data.workout_id}`;
      document.getElementById('wahoo-status').classList.add('connected');
      loadHistory();
    } else if (resp.status === 401) {
      // Not connected to Wahoo. Stash the in-progress workout so it survives the
      // OAuth round-trip — the callback redirects back to a freshly-loaded editor
      // (restored from pendingLoad at the bottom of this file).
      sessionStorage.setItem('pendingLoad', JSON.stringify({ plan_json: plan }));
      window.location.href = '/auth/wahoo';
      return;
    } else {
      statusEl.style.color = '#f44336';
      statusEl.textContent = data.detail || 'Push failed';
    }
  } catch {
    statusEl.style.color = '#f44336';
    statusEl.textContent = 'Network error';
  } finally {
    btn.disabled = false;
  }
}

async function pushGarmin() {
  if (!state.intervals.length) {
    document.getElementById('push-status').textContent = 'Add steps first';
    return;
  }
  const plan = buildPlan();
  const window_s = parseFloat(document.getElementById('pace-window').value) || 10;
  const dateVal = document.getElementById('schedule-date').value;
  const scheduled_at = dateVal ? new Date(dateVal + 'T00:00:00').toISOString() : null;

  const btn = document.getElementById('push-garmin-btn');
  const statusEl = document.getElementById('push-status');
  btn.disabled = true;
  statusEl.style.color = '#71717a';
  statusEl.textContent = 'Pushing to Garmin…';

  try {
    const resp = await fetch('/workouts/push-garmin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan, pace_window_s: window_s, scheduled_at }),
    });
    let data;
    try { data = await resp.json(); } catch { data = {}; }
    if (resp.ok) {
      statusEl.style.color = '#4caf50';
      const sched = data.scheduled_date ? ` · scheduled ${data.scheduled_date}` : '';
      statusEl.textContent = `✓ Pushed to Garmin${sched}`;
      document.getElementById('garmin-status').classList.add('connected');
      loadHistory();
    } else if (resp.status === 401) {
      btn.disabled = false;
      statusEl.textContent = '';
      window._garminRetryPush = true;
      openGarminModal();
      return;
    } else {
      statusEl.style.color = '#f44336';
      statusEl.textContent = data.detail || `Garmin push failed (${resp.status})`;
    }
  } catch (err) {
    statusEl.style.color = '#f44336';
    statusEl.textContent = `Error: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

// ── History ───────────────────────────────────────────────────────────────────


async function loadHistory() {
  const el = document.getElementById('history-list');
  try {
    const resp = await fetch('/workouts/history');
    if (!resp.ok) {
      el.innerHTML = `<span class="history-empty">Error loading history (${resp.status})</span>`;
      return;
    }
    const rows = await resp.json();
    _historyRows = rows;
    if (!rows.length) {
      el.innerHTML = '<span class="history-empty">No workouts pushed yet.</span>';
      return;
    }
    el.innerHTML = rows.map(r => {
      const dateStr = r.scheduled_at || r.pushed_at;
      const date = dateStr ? new Date(dateStr).toLocaleDateString() : '—';
      return `<div class="history-row" id="history-row-${r.id}">
        <span class="history-name">${escapeHtml(r.name)}</span>
        <span class="history-date">${date}</span>
        <button class="btn-load" onclick="loadFromHistory(${r.id})">Load</button>
        <button class="btn-delete" onclick="archiveWorkout(${r.id}, this)">Archive</button>
      </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<span class="history-empty">Failed: ${escapeHtml(e.message)}</span>`;
  }
}

async function archiveWorkout(id, btn) {
  btn.disabled = true;
  const resp = await fetch(`/workouts/${id}/archive`, { method: 'POST' });
  if (resp.ok) {
    loadHistory();
  } else {
    btn.disabled = false;
    alert('Archive failed');
  }
}

document.getElementById('schedule-date').value = new Date().toISOString().split('T')[0];
loadHistory();
render();

const _pending = sessionStorage.getItem('pendingLoad');
if (_pending) {
  sessionStorage.removeItem('pendingLoad');
  try {
    const w = JSON.parse(_pending);
    const plan = typeof w.plan_json === 'string' ? JSON.parse(w.plan_json) : w.plan_json;
    nextId = 1;
    state = planToState(plan);
    document.getElementById('workout-name').value = state.name;
    render();
  } catch {}
}
