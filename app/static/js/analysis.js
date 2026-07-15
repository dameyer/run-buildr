let allRecords = [], allLaps = [], activeMeta = {}, activeRaw = {};
const charts = {};
let activeSource = 'wahoo';

const METRICS = [
  { key: "pace",       label: "Pace (min/mi)",       fmt: v => formatPace(v),  color: "#4fc3f7", yInvert: true  },
  { key: "pace_km",    label: "Pace / km",           fmt: v => formatPace(v),  color: "#4fc3f7", yInvert: true,  xKey: "distance", xFmt: v => `${(v/1000).toFixed(1)}km` },
  { key: "heart_rate", label: "Heart Rate (bpm)",    fmt: v => v?.toFixed(0),  color: "#ef5350", yInvert: false },
  { key: "cadence",    label: "Cadence (spm)",       fmt: v => v?.toFixed(0),  color: "#81c784", yInvert: false },
  { key: "elevation",  label: "Elevation (m)",       fmt: v => v?.toFixed(0),  color: "#a5d6a7", yInvert: false, xKey: "distance", xFmt: v => `${(v/1000).toFixed(1)}km` },
  { key: "vo",         label: "Vert. Osc. (mm)",     fmt: v => v?.toFixed(1),  color: "#ffb74d", yInvert: false },
  { key: "stance",     label: "Stance Time (ms)",    fmt: v => v?.toFixed(0),  color: "#ce93d8", yInvert: false },
  { key: "stride",     label: "Stride Length (m)",   fmt: v => v?.toFixed(2),  color: "#80cbc4", yInvert: false },
  { key: "grade",      label: "Grade (%)",           fmt: v => v?.toFixed(1),  color: "#ef9a9a", yInvert: false },
];

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function formatPace(secs) {
  if (!secs) return "—";
  secs = Math.round(secs);  // round the total first so seconds never show as :60
  const m = Math.floor(secs / 60);
  const s = (secs % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function formatDuration(secs) {
  if (!secs) return "—";
  secs = Math.round(secs);  // round the total first so seconds never show as :60
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2,"0")}:${s.toString().padStart(2,"0")}`;
  return `${m}:${s.toString().padStart(2,"0")}`;
}

function setSource(src) {
  if (activeSource === src) return;
  activeSource = src;
  document.getElementById('src-wahoo').classList.toggle('active', src === 'wahoo');
  document.getElementById('src-garmin').classList.toggle('active', src === 'garmin');
  document.getElementById('analysis-panel').innerHTML = '<span class="empty">Select a workout to view analysis.</span>';
  loadWorkoutList();
}

async function loadWorkoutList() {
  const listEl = document.getElementById("workout-list");
  listEl.innerHTML = '<span class="loading">Loading…</span>';

  if (activeSource === 'garmin') {
    await loadGarminList(listEl);
  } else {
    await loadWahooList(listEl);
  }
}

async function loadWahooList(listEl) {
  try {
    const res = await fetch("/analysis/workouts");
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    if (!data.workouts.length) {
      listEl.innerHTML = '<span class="empty">No completed Wahoo workouts found.</span>';
      return;
    }
    listEl.innerHTML = data.workouts.map(w => {
      const d = w.starts ? new Date(w.starts) : null;
      const dateStr = d ? d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—";
      const mins = w.minutes ? `${w.minutes} min` : "";
      return `<div class="wk-row" onclick="loadFit('wahoo', '${w.id}', this)">
        <span class="wk-name">${escapeHtml(w.name || "Workout")}</span>
        <span class="wk-meta">${dateStr}${mins ? " · " + mins : ""}</span>
      </div>`;
    }).join("");
  } catch (e) {
    listEl.innerHTML = `<span class="error">${escapeHtml(e.message)}</span>`;
  }
}

async function loadGarminList(listEl) {
  try {
    const res = await fetch("/analysis/garmin/activities");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Error ${res.status}`);
    }
    const data = await res.json();
    if (!data.activities.length) {
      listEl.innerHTML = '<span class="empty">No Garmin running activities found.</span>';
      return;
    }
    listEl.innerHTML = data.activities.map(a => {
      const d = a.startTimeLocal ? new Date(a.startTimeLocal) : null;
      const dateStr = d ? d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—";
      const km = a.distance ? `${(a.distance / 1000).toFixed(1)} km` : "";
      const dur = a.duration ? ` · ${formatDuration(a.duration)}` : "";
      const encodedName = encodeURIComponent(a.activityName || "Run");
      return `<div class="wk-row" onclick="loadFit('garmin', '${a.activityId}', this, '${encodedName}')">
        <span class="wk-name">${escapeHtml(a.activityName || "Run")}</span>
        <span class="wk-meta">${dateStr}${km ? " · " + km : ""}${dur}</span>
      </div>`;
    }).join("");
  } catch (e) {
    listEl.innerHTML = `<span class="error">${escapeHtml(e.message)}</span>`;
  }
}

async function loadFit(source, activityId, rowEl, encodedName) {
  document.querySelectorAll(".wk-row").forEach(r => r.classList.remove("active"));
  if (rowEl) rowEl.classList.add("active");

  const panel = document.getElementById("analysis-panel");
  panel.innerHTML = '<span class="loading">Downloading & parsing FIT file…</span>';

  const url = source === 'garmin'
    ? `/analysis/garmin/fit/${activityId}?name=${encodedName || ''}`
    : `/analysis/fit/${activityId}`;

  try {
    const res = await fetch(url);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Error ${res.status}`);
    }
    const data = await res.json();
    allRecords = data.records;
    allLaps = data.laps;
    activeMeta = data.meta;
    activeRaw = data.raw || {};
    renderAnalysis();
  } catch (e) {
    panel.innerHTML = `<span class="error">${escapeHtml(e.message)}</span>`;
  }
}

function renderAnalysis() {
  const panel = document.getElementById("analysis-panel");

  const hasDev = allRecords.some(r =>
    r.form_power != null || r.leg_spring != null || r.smoothness != null
  );

  const devBadge = hasDev
    ? '<span class="dev-badge populated">Developer fields populated</span>'
    : '<span class="dev-badge empty">Developer fields empty</span>';

  panel.innerHTML = `
    <div class="meta-row">
      <span class="meta-name">${escapeHtml(activeMeta.name || "Workout")}</span>
      ${devBadge}
    </div>
    <div class="raw-bar" id="raw-bar" onclick="toggleRaw()">{ } View raw ${activeSource} data</div>
    <div id="raw-preview">
      <div class="raw-actions">
        <button class="raw-btn" onclick="copyRaw(this)">Copy</button>
        <button class="raw-btn" onclick="downloadRaw()">Download</button>
      </div>
      <pre id="raw-pre"></pre>
    </div>
    <div class="lap-table-wrap" id="lap-table-wrap"></div>
    <div class="charts-grid" id="charts-grid"></div>
  `;

  renderLapTable();
  renderCharts();
}

function rawJsonString() {
  // Wahoo's raw object is only the workout summary; append the parsed FIT file
  // data (the run's per-record metrics + laps) that drove the analytics.
  const display = activeSource === "wahoo"
    ? { ...activeRaw, fit_file: { records: allRecords, laps: allLaps } }
    : activeRaw;
  return JSON.stringify(display, null, 2);
}

function toggleRaw() {
  const preview = document.getElementById("raw-preview");
  if (preview.style.display === "block") {
    preview.style.display = "none";
  } else {
    document.getElementById("raw-pre").textContent = rawJsonString();
    preview.style.display = "block";
  }
}

async function copyRaw(btn) {
  try {
    await navigator.clipboard.writeText(rawJsonString());
    btn.textContent = "Copied";
    setTimeout(() => { btn.textContent = "Copy"; }, 1500);
  } catch {
    btn.textContent = "Copy failed";
    setTimeout(() => { btn.textContent = "Copy"; }, 1500);
  }
}

function rawFilename() {
  const name = (activeMeta.name || "workout").trim().replace(/\s+/g, "_").replace(/[\/\\:*?"<>|]/g, "");
  const s = activeMeta.starts || activeRaw.starts || activeRaw.startTimeLocal || activeRaw.startTimeGMT;
  const d = s ? new Date(s) : new Date();
  const date = isNaN(d) ? new Date() : d;
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${activeSource}_${name}_${y}_${m}_${day}.txt`;
}

function downloadRaw() {
  const blob = new Blob([rawJsonString()], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = rawFilename();
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function renderLapTable() {
  const el = document.getElementById("lap-table-wrap");
  if (!allLaps.length) { el.innerHTML = ""; return; }

  const rows = allLaps.map((lap, i) => {
    const dist = lap.distance ? (lap.distance / 1000).toFixed(2) + " km" : "—";
    const ascentCols = allLaps.some(l => l.ascent != null)
      ? `<td>${lap.ascent?.toFixed(0) ?? "—"}</td><td>${lap.descent?.toFixed(0) ?? "—"}</td>`
      : '';
    return `<tr>
      <td>Lap ${i + 1}</td>
      <td>${formatDuration(lap.duration)}</td>
      <td>${dist}</td>
      <td>${formatPace(lap.avg_pace)}</td>
      <td>${lap.avg_cadence?.toFixed(0) ?? "—"}</td>
      <td>${lap.avg_vo?.toFixed(1) ?? "—"} mm</td>
      <td>${lap.avg_stance?.toFixed(0) ?? "—"} ms</td>
      <td>${lap.avg_grade?.toFixed(1) ?? "—"} %</td>
      ${ascentCols}
    </tr>`;
  }).join("");

  const hasAscent = allLaps.some(l => l.ascent != null);
  el.innerHTML = `<table class="lap-table">
    <thead><tr>
      <th>Lap</th><th>Time</th><th>Dist</th><th>Pace</th>
      <th>Cadence</th><th>Vert Osc</th><th>Stance</th><th>Grade</th>
      ${hasAscent ? '<th>↑ m</th><th>↓ m</th>' : ''}
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function renderCharts() {
  const grid = document.getElementById("charts-grid");
  grid.innerHTML = "";

  // destroy old charts
  Object.values(charts).forEach(c => c.destroy());
  Object.keys(charts).forEach(k => delete charts[k]);

  const lapTimes = allLaps.map(l => l.start_t).filter(t => t != null && t > 0);

  METRICS.forEach(m => {
    const values = allRecords.map(r => r[m.key]);
    if (values.every(v => v == null)) return;

    const wrap = document.createElement("div");
    wrap.className = "chart-wrap";
    const canvas = document.createElement("canvas");
    wrap.appendChild(canvas);
    grid.appendChild(wrap);

    const xKey = m.xKey || "t";
    const xFmt = m.xFmt || (v => formatDuration(Math.round(v)));
    const tooltipXFmt = m.xKey ? (v => `${(v/1000).toFixed(2)} km`) : (v => formatDuration(Math.round(v)));

    const pts = allRecords
      .map(r => ({ x: r[xKey], y: r[m.key] }))
      .filter(p => p.x != null && p.y != null);

    const lapPlugin = {
      id: `lapLines_${m.label}`,
      afterDraw(chart) {
        if (xKey !== "t" || !lapTimes.length) return;
        const { ctx, scales } = chart;
        ctx.save();
        ctx.strokeStyle = "rgba(0,0,0,0.12)";
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 5]);
        lapTimes.forEach(t => {
          const x = scales.x.getPixelForValue(t);
          ctx.beginPath();
          ctx.moveTo(x, chart.chartArea.top);
          ctx.lineTo(x, chart.chartArea.bottom);
          ctx.stroke();
        });
        ctx.restore();
      }
    };

    const yOpts = m.yInvert
      ? { reverse: true, ticks: { callback: v => formatPace(v) } }
      : {};

    const chartKey = `${m.key}_${xKey}`;
    charts[chartKey] = new Chart(canvas, {
      type: "line",
      data: {
        datasets: [{
          data: pts,
          borderColor: m.color,
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.3,
          fill: m.key === "elevation" ? { target: "origin", above: "rgba(165,214,167,0.15)" } : false,
        }]
      },
      options: {
        animation: false,
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          title: {
            display: true,
            text: m.label,
            color: "#71717a",
            font: { size: 11 },
            padding: { bottom: 4 },
          },
          tooltip: {
            callbacks: {
              label: ctx => m.fmt(ctx.parsed.y),
              title: ctx => tooltipXFmt(ctx[0].parsed.x),
            }
          }
        },
        scales: {
          x: {
            type: "linear",
            ticks: {
              color: "#a1a1aa",
              font: { size: 10 },
              maxTicksLimit: 8,
              callback: xFmt,
            },
            grid: { color: "#e8e8eb" },
          },
          y: {
            ticks: { color: "#a1a1aa", font: { size: 10 }, ...(yOpts.ticks || {}) },
            grid: { color: "#e8e8eb" },
            ...(m.yInvert ? { reverse: true } : {}),
          }
        }
      },
      plugins: [lapPlugin],
    });
  });
}

loadWorkoutList();
