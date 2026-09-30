const $ = (id) => document.getElementById(id);
// /edit?id=7 edits that record, /new creates one
const EDIT_ID = location.pathname === "/edit" ? Number(new URLSearchParams(location.search).get("id")) : null;
const TEXT_FIELDS = ["sample_name", "experiment_date", "responsible_person", "sample_type", "reference_type",
  "material", "substrate", "treatment", "description", "slug"];
const NUMBER_FIELDS = ["thickness_nm", "substrate_thickness_um", "temperature_K"];
// experiment parameters, stored in the record's `source`; third item is the typical
// value, an optional fourth the fixed choices. Shown three per row.
const SOURCE_FIELDS = [
  ["laser", "Laser", "Pharos Standard", ["Pharos Standard", "Pharos CryoStation"]],
  ["rep_rate", "Rep. rate", "10kHz"],
  ["attenuation", "Attenuation", "100%"],
  ["thz_source", "THz source", "2mm GaP"],
  ["pump_power", "Pump power", "500mW"],
  ["focusing", "Focusing", "Collimated"],
  ["thz_detection", "THz detection", "2mm GaP"],
  ["probe_power", "Probe power", "700uW"],
];
const ROLES = [["reference", "reference"], ["sample", "sample"], ["reference_echo", "reference echo"], ["sample_echo", "sample echo"]];

for (const [key, title, typical, choices] of SOURCE_FIELDS) {
  const label = document.createElement("label");
  label.textContent = title + " ";
  if (choices) {
    const select = Object.assign(document.createElement("select"), { id: "s-" + key });
    for (const value of choices) select.append(new Option(value));
    select.value = typical;
    label.append(select);
    $("source-fields").append(label);
    continue;
  }
  const input = Object.assign(document.createElement("input"), { id: "s-" + key, placeholder: typical });
  input.setAttribute("list", "typical-" + key);
  const list = Object.assign(document.createElement("datalist"), { id: "typical-" + key });
  list.append(Object.assign(document.createElement("option"), { value: typical }));
  label.append(input, list);
  $("source-fields").append(label);
}
$("fill-typical").onclick = () => {
  for (const [key, , typical] of SOURCE_FIELDS) if (!$("s-" + key).value.trim()) $("s-" + key).value = typical;
};

async function detail(r, fallback) {
  try {
    const d = (await r.json()).detail;
    return typeof d === "string" ? d : fallback;
  } catch { return fallback; }
}

// ---- key: value textareas
function dictToText(obj) {
  return Object.entries(obj || {}).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join("\n");
}
function textToDict(text) {
  const out = {};
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    const i = line.indexOf(":");
    if (i < 1) throw new Error(`"${line.trim()}" is not in the form key: value`);
    const value = line.slice(i + 1).trim();
    out[line.slice(0, i).trim()] = value !== "" && !isNaN(Number(value)) ? Number(value) : value;
  }
  return out;
}

// ---- waveform rows
function addWaveform(w = {}) {
  const row = document.createElement("div");
  row.className = "waveform";
  row.innerHTML = `
    <div class="controls">
      <label>Role <select class="role">${ROLES.map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select></label>
      <label>Label <input class="label" value="main" required></label>
      <label class="file">File <input class="file-input" type="file" required><span class="expected"></span></label>
      <label class="generic">Time unit <select class="unit"><option>ps</option><option>fs</option><option>ns</option><option>s</option></select></label>
      <label class="generic">Time column <input class="tcol" type="number" min="1" max="50" value="1" required></label>
      <label class="generic">Field column <input class="ecol" type="number" min="1" max="50" value="2" required></label>
      <button type="button" class="link remove">Remove</button>
      <button type="button" class="edit-waveform" disabled>Edit waveform</button>
    </div>
    <div class="preview"><div class="plots"><div class="plot"></div><div class="fft"></div></div><div class="info">Choose a file to see the waveform and its spectrum.</div><div class="treatment-summary"></div></div>`;
  const q = (sel) => row.querySelector(sel);
  if (w.role) q(".role").value = w.role;
  if (w.label) q(".label").value = w.label;
  if (w.time_unit) q(".unit").value = w.time_unit;
  if (w.time_column != null) q(".tcol").value = Number(w.time_column) + 1;
  if (w.amplitude_column != null) q(".ecol").value = Number(w.amplitude_column) + 1;
  if (w.file) q(".expected").textContent = `metadata file names: ${w.file}`;
  for (const sel of [".file-input", ".unit", ".tcol", ".ecol"]) q(sel).onchange = () => preview(row);
  q(".edit-waveform").onclick = () => openTreatmentEditor(row);
  q(".remove").onclick = () => { Plotly.purge(q(".plot")); Plotly.purge(q(".fft")); row.remove(); };
  $("waveforms").append(row);
  if (w.stored) {
    // a waveform that is already in the database: keep it unless a new file is chosen
    row.dataset.id = w.id;
    row.stored = w.stored;
    row.treatment = w.treatment && Object.keys(w.treatment).length ? w.treatment : null;
    q(".file-input").required = false;
    q("label.file").firstChild.textContent = "Replace with file ";
    q(".expected").textContent = `stored: ${w.source_file}`;
    show(row, w.stored);
  }
  return row;
}

const PLOT_FONT = { size: 10 };
// `after`: optional treated data drawn in blue over the measured data in grey
function smallPlot(el, x, y, xTitle, log, after) {
  const traces = [{ x, y, mode: "lines", line: { width: 1.2, color: after ? "#98a2b3" : "#2f6fdb" }, hoverinfo: "x+y" }];
  if (after) traces.push({ x: after.x, y: after.y, mode: "lines", line: { width: 1.4, color: "#2f6fdb" }, hoverinfo: "x+y" });
  Plotly.react(el, traces, {
    margin: { l: 48, r: 8, t: 8, b: 34 },
    xaxis: { title: { text: xTitle, standoff: 4, font: { size: 11 } }, zeroline: false, tickfont: PLOT_FONT },
    yaxis: { type: log ? "log" : "linear", zeroline: !log, zerolinecolor: "#d9dde3", tickfont: PLOT_FONT, exponentformat: "e" },
    showlegend: false,
  }, { responsive: true, displayModeBar: false });
}

function localDate(iso) {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function clock(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

// what a lab file says about itself, shown under the plots
function describeInfo(d) {
  const i = d.info;
  const lines = [];
  if (i.format === "lab") {
    lines.push(`Lab file: averaged x (V) against delay (ps); average of ${i.n_averages} scan${i.n_averages === 1 ? "" : "s"} (${i.average_source}).`);
    lines.push(`${i.n_points} points · delay span ${i.delay_span_ps} ps (${d.t_min} to ${d.t_max} ps) · step ${i.step_ps} ps`);
    if (i.measured_start_utc) {
      lines.push(`Measured ${localDate(i.measured_start_utc)}, ${clock(i.measured_start_utc)} to ${clock(i.measured_end_utc)} (${(i.duration_s / 60).toFixed(1)} min)`);
    }
    if (i.kmm1_v != null) lines.push(`KMM1 ${i.kmm1_v.toPrecision(5)} V · KMM2 ${i.kmm2_v.toPrecision(5)} V (mean of the last two columns)`);
    if (i.notes.length) lines.push("Notes in file: " + i.notes.join(" | "));
  } else {
    lines.push(`${d.n_points} points · ${d.t_min.toPrecision(4)} to ${d.t_max.toPrecision(4)} ps · step ${d.dt.toPrecision(3)} ps`);
  }
  return lines;
}

function show(row, d) {
  const q = (sel) => row.querySelector(sel);
  row.data = d;  // what the treatment editor works on
  q(".edit-waveform").disabled = false;
  showTreatment(row);
  const info = q(".info");
  info.classList.remove("error");
  row.classList.toggle("lab", d.info.format === "lab");
  info.replaceChildren(...describeInfo(d).map((text) => Object.assign(document.createElement("div"), { textContent: text })));
  drawRowPlots(row);
}

// the row's two small plots; with a treatment set, measured (grey) and treated (blue)
async function drawRowPlots(row) {
  const q = (sel) => row.querySelector(sel);
  const d = row.data, treatment = row.treatment;
  const timeTitle = d.info.format === "lab" ? "Delay (ps)" : "Time (ps)";
  const draw = (res) => {
    smallPlot(q(".plot"), d.t, d.e, timeTitle, false, res && { x: res.t_after, y: res.e_after });
    smallPlot(q(".fft"), d.freq_thz, d.fft_abs, "|FFT| vs frequency (THz)", true, res && { x: res.fft_after.freq_thz, y: res.fft_after.abs });
  };
  if (!treatment) { draw(null); return; }
  const r = await treatRequest(treatment, row);
  if (row.data !== d || row.treatment !== treatment) return;
  draw(r.ok ? await r.json() : null);
}

async function preview(row) {
  const q = (sel) => row.querySelector(sel);
  const file = q(".file-input").files[0];
  const info = q(".info");
  if (file) row.treatment = null;  // settings belong to the previous data
  const clear = (text, error) => {
    row.data = null;
    q(".edit-waveform").disabled = true;
    showTreatment(row);
    Plotly.purge(q(".plot"));
    Plotly.purge(q(".fft"));
    info.classList.toggle("error", !!error);
    info.textContent = text;
  };
  if (!file && row.stored) { show(row, row.stored); return; }
  row.classList.remove("lab");
  if (!file) { clear("Choose a file to see the waveform and its spectrum."); return; }
  const body = new FormData();
  body.append("file", file);
  body.append("time_unit", q(".unit").value);
  body.append("time_column", q(".tcol").value - 1);
  body.append("amplitude_column", q(".ecol").value - 1);
  info.classList.remove("error");
  info.textContent = "Reading…";
  const r = await fetch("/api/admin/preview-waveform", { method: "POST", body });
  if (file !== q(".file-input").files[0]) return;
  if (!r.ok) { clear(await detail(r, "Could not read this file."), true); return; }
  const d = await r.json();
  show(row, d);
  if (d.info.measured_start_utc && !$("f-experiment_date").value) {
    $("f-experiment_date").value = localDate(d.info.measured_start_utc);
  }
}

// ---- metadata file -> form
function fill(meta) {
  for (const f of [...TEXT_FIELDS, ...NUMBER_FIELDS]) {
    if (meta[f] != null) $("f-" + f).value = String(meta[f]).trim();
  }
  // known experiment parameters go to their fields, anything else to "Other parameters"
  const other = { ...(meta.extra && typeof meta.extra === "object" ? meta.extra : {}) };
  for (const [key, value] of Object.entries(meta.source && typeof meta.source === "object" ? meta.source : {})) {
    const field = $("s-" + key);
    if (field) {
      // a fixed-choice field keeps its default when the stored value is not one of the choices
      if (field.tagName !== "SELECT" || [...field.options].some((o) => o.value === String(value))) field.value = String(value);
    }
    else other[key] = value;
  }
  if (Object.keys(other).length) $("f-extra").value = dictToText(other);
  if (Array.isArray(meta.waveforms) && meta.waveforms.length) {
    // keep rows that already have a file or stored data; replace the empty ones
    for (const row of [...$("waveforms").children]) {
      if (!row.querySelector(".file-input").files.length && !row.stored) row.remove();
    }
    const have = new Set([...$("waveforms").children].map((r) => r.querySelector(".role").value + "/" + r.querySelector(".label").value));
    for (const w of meta.waveforms) {
      if (w && !have.has(w.role + "/" + (w.label || "main"))) addWaveform(w);
    }
  }
}

$("meta-file").onchange = async () => {
  const file = $("meta-file").files[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  const r = await fetch("/api/admin/parse-metadata", { method: "POST", body });
  const msg = $("meta-message");
  msg.classList.toggle("error", !r.ok);
  if (r.ok) {
    fill(await r.json());
    msg.textContent = `Loaded ${file.name} – check the fields and choose the waveform files.`;
  } else {
    msg.textContent = await detail(r, "Could not read the metadata file.");
  }
  $("meta-file").value = "";
};

// ---- submit
$("record").onsubmit = async (e) => {
  e.preventDefault();
  const message = $("message");
  message.textContent = "";
  const meta = {};
  try {
    for (const f of TEXT_FIELDS) meta[f] = $("f-" + f).value.trim();
    for (const f of NUMBER_FIELDS) meta[f] = $("f-" + f).value === "" ? null : Number($("f-" + f).value);
    meta.extra = textToDict($("f-extra").value);
    meta.source = {};
    for (const [key] of SOURCE_FIELDS) if ($("s-" + key).value.trim()) meta.source[key] = $("s-" + key).value.trim();
  } catch (err) {
    message.textContent = err.message;
    return;
  }
  const rows = [...$("waveforms").children];
  const keys = rows.map((r) => r.querySelector(".role").value + "/" + r.querySelector(".label").value.trim());
  for (const needed of ["reference/main", "sample/main"]) {
    if (!keys.includes(needed)) { message.textContent = `A ${needed.split("/")[0]} waveform with label "main" is required.`; return; }
  }
  if (new Set(keys).size !== keys.length) { message.textContent = "Two waveforms have the same role and label."; return; }

  const body = new FormData();
  let uploads = 0;
  meta.waveforms = rows.map((row) => {
    const q = (sel) => row.querySelector(sel);
    const w = {
      role: q(".role").value, label: q(".label").value.trim(), time_unit: q(".unit").value,
      time_column: q(".tcol").value - 1, amplitude_column: q(".ecol").value - 1,
    };
    if (row.treatment) w.treatment = row.treatment;
    const file = q(".file-input").files[0];
    if (file) {
      body.append("files", file);
      w.upload = uploads++;
    } else {
      w.id = Number(row.dataset.id);
    }
    return w;
  });
  body.append("metadata", JSON.stringify(meta));

  $("save").disabled = true;
  const r = EDIT_ID
    ? await fetch("/api/admin/records/" + EDIT_ID, { method: "PUT", body })
    : await fetch("/api/admin/records", { method: "POST", body });
  $("save").disabled = false;
  if (!r.ok) {
    message.textContent = await detail(r, "Saving failed.");
    return;
  }
  const saved = await r.json();
  $("done-slug").textContent = saved.slug;
  $("done-view").href = "/?select=" + saved.id;
  if (EDIT_ID) {
    $("done-title").textContent = "Changes saved";
    Object.assign($("done-again"), { href: "/edit?id=" + EDIT_ID, textContent: "Continue editing" });
  }
  $("record").hidden = true;
  $("done").hidden = false;
  scrollTo(0, 0);
};

// ---- edit mode: load the record and its history
const when = (iso) => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short", hour12: false });

const COMPARE = [
  ["sample_name", "Sample name"], ["sample_type", "Sample type"], ["reference_type", "Reference"],
  ["material", "Material"], ["thickness_nm", "Thickness (nm)"], ["substrate", "Substrate"],
  ["substrate_thickness_um", "Substrate thickness (µm)"], ["temperature_k", "Temperature (K)"],
  ["treatment", "Treatment"], ["experiment_date", "Experiment date"], ["responsible_person", "Responsible person"],
  ["source", "Experiment parameters"], ["description", "Other experiment details"], ["extra", "Other parameters"],
];
function cellText(value) {
  if (value == null || value === "") return "";
  return typeof value === "object" ? dictToText(value) : String(value);
}
function waveformText(list) {
  return list.map((w) => `${w.role.replace("_", " ")}${w.label === "main" ? "" : " / " + w.label}: ${w.source_file} (${w.n_points} points)`
    + (w.treatment && Object.keys(w.treatment).length ? `\n   treatment: ${treatmentText(w.treatment)}` : "")).join("\n");
}

async function showVersion(record, entry) {
  const r = await fetch(`/api/admin/records/${EDIT_ID}/versions/${entry.version}`);
  if (!r.ok) return;
  const old = (await r.json()).snapshot;
  $("version-title").textContent = entry.version === 1
    ? "Original version"
    : `Version before the edit of ${when(entry.edited_at)}`;
  const rows = COMPARE.map(([key, title]) => [title, cellText(old.measurement[key]), cellText(record.measurement[key])]);
  rows.push(["Waveforms", waveformText(old.waveforms), waveformText(record.waveforms)]);
  const table = $("version-table");
  table.replaceChildren();
  const head = table.insertRow();
  for (const text of ["", "This version", "Current"]) head.append(Object.assign(document.createElement("th"), { textContent: text }));
  for (const [title, before, now] of rows) {
    const tr = table.insertRow();
    tr.classList.toggle("changed", before !== now);
    for (const text of [title, before, now]) tr.insertCell().textContent = text;
  }
  $("version-dialog").showModal();
}
$("version-close").onclick = () => $("version-dialog").close();

async function loadRecord() {
  const r = await fetch("/api/admin/records/" + EDIT_ID);
  if (!r.ok) {
    $("message").textContent = await detail(r, "Could not load the record.");
    $("save").disabled = true;
    return;
  }
  const record = await r.json();
  const m = record.measurement;
  document.title = "Edit record – THz transmission database";
  $("title").textContent = "Edit record";
  $("save").textContent = "Save changes";
  $("added-by").textContent = `${m.added_by} on ${when(m.added_at)}`;
  $("f-slug").readOnly = true;
  fill({ ...m, temperature_K: m.temperature_k });
  for (const w of record.waveforms) addWaveform({ ...w, stored: w.preview });

  if (record.history.length) {
    const last = record.history[record.history.length - 1];
    const n = record.history.length;
    $("edited-note").textContent = `This record was edited${n > 1 ? ` ${n} times, last` : ""} on ${when(last.edited_at)} by ${last.edited_by}. Previous versions are listed at the bottom of this page.`;
    $("edited-note").hidden = false;
    $("history").hidden = false;
    $("history-list").replaceChildren(...record.history.map((entry) => {
      const li = document.createElement("li");
      li.textContent = `Edited on ${when(entry.edited_at)} by ${entry.edited_by} · `;
      const b = Object.assign(document.createElement("button"), {
        type: "button", className: "link",
        textContent: entry.version === 1 ? "show the original version" : "show the version before this edit",
      });
      b.onclick = () => showVersion(record, entry);
      li.append(b);
      return li;
    }));
  }
}

// ---- account
$("logout").onclick = async () => { await fetch("/api/auth/logout", { method: "POST" }); location.href = "/"; };
$("change-password").onclick = () => { $("password-form").reset(); $("pw-message").textContent = ""; $("password-dialog").showModal(); };
$("pw-cancel").onclick = () => $("password-dialog").close();
$("password-form").onsubmit = async (e) => {
  e.preventDefault();
  const r = await fetch("/api/auth/password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current: $("pw-current").value, new: $("pw-new").value }),
  });
  if (r.ok) $("password-dialog").close();
  else $("pw-message").textContent = await detail(r, "Could not change the password.");
};

(async () => {
  const r = await fetch("/api/auth/me");
  if (!r.ok) { location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search); return; }
  const me = await r.json();
  $("who").textContent = me.email;
  $("added-by").textContent = me.name || me.email;
  $("record").hidden = false;
  if (EDIT_ID) {
    await loadRecord();
  } else {
    addWaveform({ role: "reference" });
    addWaveform({ role: "sample" });
  }
  $("add-waveform").onclick = () => {
    const used = [...$("waveforms").children].map((r) => r.querySelector(".role").value);
    addWaveform({ role: used.includes("reference_echo") ? "sample_echo" : "reference_echo" });
  };
})();
