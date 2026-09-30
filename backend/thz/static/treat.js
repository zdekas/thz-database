// Waveform treatment editor: baseline subtraction, trimming, apodization.
// All numbers come from the server (/api/admin/treat-preview), which runs the
// same code as the analysis; this file only handles the controls and plots.

const T = { row: null, state: null, suggested: null, shapes: [], seq: 0, timer: null };
const tEl = (id) => document.getElementById("t-" + id);
const T_FIELDS = [["baseline", "from"], ["baseline", "to"], ["trim", "from"], ["trim", "to"], ["apod", "centre"], ["apod", "width"]];
const T_SLIDERS = [["trim", "from"], ["trim", "to"], ["apod", "centre"], ["apod", "width"]];
const round = (v) => Math.round(v * 1000) / 1000;

function treatmentText(t) {
  const parts = [];
  if (t.baseline) parts.push(`baseline from ${round(t.baseline.from_ps)} to ${round(t.baseline.to_ps)} ps subtracted`);
  if (t.trim) parts.push(`trimmed to ${round(t.trim.from_ps)} … ${round(t.trim.to_ps)} ps`);
  if (t.apodization) parts.push(`apodized ±${round(t.apodization.width_ps)} ps around ${round(t.apodization.centre_ps)} ps`);
  return parts.join("; ");
}

function showTreatment(row) {
  const el = row.querySelector(".treatment-summary");
  el.textContent = row.treatment ? "Grey: as measured, blue: after treatment (" + treatmentText(row.treatment) + ")" : "";
}

// stored form <-> editor state (every step keeps its numbers even while switched off)
function toState(treatment, s) {
  const t = treatment || {};
  return {
    baseline: { on: !!t.baseline, from: (t.baseline || s.baseline).from_ps, to: (t.baseline || s.baseline).to_ps },
    trim: { on: !!t.trim, from: (t.trim || s.trim).from_ps, to: (t.trim || s.trim).to_ps },
    apod: { on: !!t.apodization, centre: (t.apodization || s.apodization).centre_ps, width: (t.apodization || s.apodization).width_ps },
  };
}
function toTreatment(s) {
  const out = {};
  if (s.baseline.on) out.baseline = { from_ps: s.baseline.from, to_ps: s.baseline.to };
  if (s.trim.on) out.trim = { from_ps: s.trim.from, to_ps: s.trim.to };
  if (s.apod.on) out.apodization = { centre_ps: s.apod.centre, width_ps: s.apod.width };
  return Object.keys(out).length ? out : null;
}

async function treatRequest(treatment, row = T.row) {
  const d = row.data;
  return fetch("/api/admin/treat-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ t: d.t, e: d.e, treatment }),
  });
}

function writeControls() {
  for (const step of ["baseline", "trim", "apod"]) tEl(step + "-on").checked = T.state[step].on;
  for (const [step, key] of T_FIELDS) tEl(`${step}-${key}`).value = round(T.state[step][key]);
  for (const [step, key] of T_SLIDERS) tEl(`${step}-${key}-s`).value = T.state[step][key];
}

async function openTreatmentEditor(row) {
  T.row = row;
  const d = row.data;
  const r = await treatRequest(null);
  if (!r.ok) return;
  T.suggested = (await r.json()).suggested;
  T.state = toState(row.treatment, T.suggested);

  const t0 = d.t[0], t1 = d.t[d.t.length - 1], step = (t1 - t0) / (d.t.length - 1);
  for (const [s, key] of T_SLIDERS) {
    const slider = tEl(`${s}-${key}-s`);
    Object.assign(slider, key === "width" ? { min: step, max: t1 - t0, step } : { min: t0, max: t1, step });
  }
  const role = row.querySelector(".role").selectedOptions[0].textContent;
  $("treat-title").textContent = `Edit waveform · ${role}`;
  $("treat-message").textContent = "";
  writeControls();
  $("treat-dialog").showModal();
  Plotly.purge("treat-time");
  Plotly.purge("treat-fft");
  refreshTreatment();
}

function scheduleTreatment() {
  clearTimeout(T.timer);
  T.timer = setTimeout(refreshTreatment, 60);
}

async function refreshTreatment() {
  const seq = ++T.seq;
  const r = await treatRequest(toTreatment(T.state));
  if (seq !== T.seq) return;
  if (!r.ok) {
    $("treat-message").textContent = await detail(r, "These settings cannot be applied.");
    return;
  }
  $("treat-message").textContent = "";
  drawTreatment(await r.json());
}

function drawTreatment(res) {
  const d = T.row.data, s = T.state;
  const grey = "#98a2b3", blue = "#2f6fdb", orange = "#e08a1e", green = "#2a9d6f";
  const traces = [
    { x: d.t, y: d.e, name: "as measured", mode: "lines", line: { width: 1.2, color: grey } },
    { x: res.t_after, y: res.e_after, name: "after treatment", mode: "lines", line: { width: 1.6, color: blue } },
  ];
  if (res.window) {
    traces.push({ x: d.t, y: res.window, name: "apodization window", yaxis: "y2", mode: "lines", line: { width: 1.4, color: orange } });
  }
  // draggable shapes; T.shapes remembers what each one stands for
  const band = (x0, x1, color) => ({ type: "rect", xref: "x", yref: "paper", x0, x1, y0: 0, y1: 1, fillcolor: color, opacity: 0.13, line: { width: 1, color } });
  const line = (x) => ({ type: "line", xref: "x", yref: "paper", x0: x, x1: x, y0: 0, y1: 1, line: { width: 2, color: "#1c2330", dash: "dash" } });
  T.shapes = [];
  const shapes = [];
  if (s.baseline.on) { T.shapes.push("baseline"); shapes.push(band(s.baseline.from, s.baseline.to, green)); }
  if (s.apod.on) { T.shapes.push("apod"); shapes.push(band(s.apod.centre - s.apod.width, s.apod.centre + s.apod.width, orange)); }
  if (s.trim.on) { T.shapes.push("trim-from", "trim-to"); shapes.push(line(s.trim.from), line(s.trim.to)); }

  const font = { family: "system-ui, sans-serif", size: 11 };
  Plotly.react("treat-time", traces, {
    margin: { l: 55, r: 40, t: 30, b: 40 }, font, shapes, uirevision: "keep",
    xaxis: { title: { text: d.info.format === "lab" ? "Delay (ps)" : "Time (ps)" }, zeroline: false },
    yaxis: { zeroline: true, zerolinecolor: "#d9dde3", exponentformat: "e" },
    yaxis2: { overlaying: "y", side: "right", range: [0, 1.05], showgrid: false, zeroline: false, tickfont: { color: orange } },
    legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom" },
  }, { responsive: true, displayModeBar: false, edits: { shapePosition: true } });
  Plotly.react("treat-fft", [
    { x: res.fft_before.freq_thz, y: res.fft_before.abs, name: "as measured", mode: "lines", line: { width: 1.2, color: grey } },
    { x: res.fft_after.freq_thz, y: res.fft_after.abs, name: "after treatment", mode: "lines", line: { width: 1.6, color: blue } },
  ], {
    margin: { l: 55, r: 10, t: 30, b: 40 }, font, uirevision: "keep", showlegend: false,
    xaxis: { title: { text: "|FFT| vs frequency (THz)" }, zeroline: false },
    yaxis: { type: "log", exponentformat: "e" },
  }, { responsive: true, displayModeBar: false });

  const plot = $("treat-time");
  if (!plot.dragHooked) {
    plot.dragHooked = true;
    plot.on("plotly_relayout", (change) => {
      const moved = {};
      for (const [key, value] of Object.entries(change)) {
        const m = /^shapes\[(\d+)\]\.(x0|x1)$/.exec(key);
        if (m) (moved[m[1]] ||= {})[m[2]] = Number(value);
      }
      for (const [index, x] of Object.entries(moved)) {
        const kind = T.shapes[index], shape = plot.layout.shapes[index];
        const x0 = round(x.x0 ?? shape.x0), x1 = round(x.x1 ?? shape.x1);
        if (kind === "baseline") Object.assign(T.state.baseline, { from: Math.min(x0, x1), to: Math.max(x0, x1) });
        if (kind === "apod") Object.assign(T.state.apod, { centre: round((x0 + x1) / 2), width: round(Math.abs(x1 - x0) / 2) });
        if (kind === "trim-from") T.state.trim.from = (x0 + x1) / 2;
        if (kind === "trim-to") T.state.trim.to = (x0 + x1) / 2;
      }
      if (Object.keys(moved).length) { writeControls(); scheduleTreatment(); }
    });
  }
}

for (const step of ["baseline", "trim", "apod"]) {
  tEl(step + "-on").onchange = (e) => { T.state[step].on = e.target.checked; scheduleTreatment(); };
}
for (const [step, key] of T_FIELDS) {
  tEl(`${step}-${key}`).oninput = (e) => {
    if (e.target.value === "" || isNaN(Number(e.target.value))) return;
    T.state[step][key] = Number(e.target.value);
    const slider = tEl(`${step}-${key}-s`);
    if (slider) slider.value = T.state[step][key];
    scheduleTreatment();
  };
}
for (const [step, key] of T_SLIDERS) {
  tEl(`${step}-${key}-s`).oninput = (e) => {
    T.state[step][key] = Number(e.target.value);
    tEl(`${step}-${key}`).value = round(T.state[step][key]);
    T.state[step].on = true;
    tEl(step + "-on").checked = true;
    scheduleTreatment();
  };
}
tEl("peak").onclick = () => {
  T.state.apod.centre = T.suggested.apodization.centre_ps;
  T.state.apod.on = true;
  writeControls();
  scheduleTreatment();
};
$("treat-apply").onclick = async () => {
  // only settings the server accepts can be applied
  const treatment = toTreatment(T.state);
  const r = await treatRequest(treatment);
  if (!r.ok) { $("treat-message").textContent = await detail(r, "These settings cannot be applied."); return; }
  T.row.treatment = treatment ? (await r.json()).treatment : null;
  showTreatment(T.row);
  drawRowPlots(T.row);
  $("treat-dialog").close();
};
$("treat-cancel").onclick = () => $("treat-dialog").close();
$("treat-clear").onclick = () => {
  T.state = toState(null, T.suggested);
  writeControls();
  scheduleTreatment();
};
