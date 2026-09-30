const X_AXES = [
  ["thz", "Frequency (THz)", "THz"],
  ["cm-1", "Wavenumber (cm⁻¹)", "cm⁻¹"],
  ["um", "Wavelength (µm)", "µm"],
  ["mev", "Energy (meV)", "meV"],
];
const Y_AXES = [
  ["abs", "|T|", "|T|"],
  ["delay", "Delay arg(T)/ω (ps)", "delay"],
  ["phase", "Phase arg(T) (rad)", "phase"],
];
const COLORS = ["#2f6fdb", "#d1495b", "#2a9d6f", "#e08a1e", "#7b4fc4", "#1b9aaa", "#a6611a", "#c2409b", "#5c6b7a", "#8a9a1c"];

const state = { x: "thz", y: "abs", full: false, selected: new Map(), results: [] };
const $ = (id) => document.getElementById(id);

function axisButtons(container, axes, key) {
  for (const [value, title, short] of axes) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = short;
    b.title = title;
    b.classList.toggle("active", state[key] === value);
    b.onclick = () => {
      state[key] = value;
      for (const other of container.querySelectorAll("button")) other.classList.toggle("active", other === b);
      updateUnit();
      draw();
    };
    container.append(b);
  }
}

function updateUnit() {
  $("interp-unit").textContent = "in " + X_AXES.find((a) => a[0] === state.x)[2];
}

function describe(m) {
  const bits = [m.experiment_date, m.material];
  if (m.thickness_nm != null) bits.push(m.thickness_nm < 1000 ? `${m.thickness_nm} nm` : `${m.thickness_nm / 1000} µm`);
  if (m.temperature_k != null) bits.push(`${m.temperature_k} K`);
  if (m.treated) bits.push("treated");
  bits.push(m.sample_type === "thin_film" ? `film on ${m.substrate || "substrate"}` : "bulk", m.responsible_person);
  return bits.filter(Boolean).join(" · ");
}

function item(m, color) {
  const li = document.createElement("li");
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = m.sample_name;
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = describe(m);
  li.append(name, meta);
  li.title = [m.slug, m.description, m.treatment && `treatment: ${m.treatment}`, `added by ${m.added_by}`]
    .filter(Boolean).join("\n");
  if (color) li.style.borderLeftColor = color;
  li.onclick = () => {
    if (state.selected.has(m.id)) state.selected.delete(m.id);
    else state.selected.set(m.id, m);
    renderLists();
    draw();
  };
  return li;
}

function renderLists() {
  const selected = [...state.selected.values()];
  $("selected-title").hidden = selected.length === 0;
  $("selected").replaceChildren(...selected.map((m, i) => item(m, COLORS[i % COLORS.length])));
  const rest = state.results.filter((m) => !state.selected.has(m.id));
  $("results-title").textContent = $("search").value.trim() ? `Matches (${rest.length})` : `Samples (${rest.length})`;
  if (rest.length) {
    $("results").replaceChildren(...rest.map((m) => item(m)));
  } else {
    const li = document.createElement("li");
    li.className = "none";
    li.textContent = state.results.length ? "All matches are selected." : "Nothing found.";
    $("results").replaceChildren(li);
  }
  for (const id of ["download", "download-interp"]) $(id).disabled = selected.length === 0;
  // editing works on one record at a time
  const edit = $("edit");
  edit.classList.toggle("disabled", selected.length !== 1);
  if (selected.length === 1) {
    edit.href = "/edit?id=" + selected[0].id;
    edit.title = "";
  } else {
    edit.removeAttribute("href");
    edit.title = "Select exactly one record to edit it";
  }
}

let searchSeq = 0;
async function search() {
  const seq = ++searchSeq;
  const r = await fetch("/api/measurements?q=" + encodeURIComponent($("search").value));
  const rows = await r.json();
  if (seq !== searchSeq) return;
  state.results = rows;
  renderLists();
}

function query(extra = {}) {
  return new URLSearchParams({ ids: [...state.selected.keys()].join(","), x: state.x, y: state.y, full: state.full, ...extra });
}

let drawSeq = 0;
async function draw() {
  const seq = ++drawSeq;
  $("message").textContent = "";
  if (state.selected.size === 0) {
    Plotly.purge("plot");
    $("plot").replaceChildren(Object.assign(document.createElement("p"), { id: "empty", textContent: "Select one or more samples on the left." }));
    return;
  }
  const r = await fetch("/api/spectra?" + query());
  if (seq !== drawSeq) return;
  if (!r.ok) {
    $("message").textContent = (await r.json()).detail || "Could not load data.";
    return;
  }
  const data = await r.json();
  $("empty")?.remove();
  const traces = data.series.map((s, i) => ({
    x: s.x, y: s.y, name: s.label, mode: "lines", line: { width: 1.8, color: COLORS[i % COLORS.length] },
    hovertemplate: "%{x:.4g}, %{y:.4g}<extra>" + s.label.replace(/</g, "&lt;") + "</extra>",
  }));
  Plotly.react("plot", traces, {
    margin: { l: 70, r: 20, t: 30, b: 55 },
    xaxis: { title: { text: X_AXES.find((a) => a[0] === state.x)[1] }, zeroline: false, showline: true, mirror: true, ticks: "outside" },
    yaxis: { title: { text: Y_AXES.find((a) => a[0] === state.y)[1] }, zeroline: false, showline: true, mirror: true, ticks: "outside" },
    showlegend: true,
    legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom" },
    font: { family: "system-ui, sans-serif", size: 13 },
    uirevision: state.x + state.y + state.full,
  }, { responsive: true, displaylogo: false });
}

async function download(extra) {
  $("message").textContent = "";
  const r = await fetch("/api/export?" + query(extra));
  if (!r.ok) {
    $("message").textContent = (await r.json()).detail || "Download failed.";
    return;
  }
  const name = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "")?.[1] || "thz_export.txt";
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(await r.blob()), download: name });
  a.click();
  URL.revokeObjectURL(a.href);
}

axisButtons($("x-axis"), X_AXES, "x");
axisButtons($("y-axis"), Y_AXES, "y");
updateUnit();
let timer;
$("search").oninput = () => { clearTimeout(timer); timer = setTimeout(search, 120); };
$("clear").onclick = () => { state.selected.clear(); renderLists(); draw(); };
$("full").onchange = (e) => { state.full = e.target.checked; draw(); };
$("download").onclick = () => download();
$("download-interp").onclick = () => download({ interp: $("interp").value });
$("interp").onkeydown = (e) => { if (e.key === "Enter" && state.selected.size) download({ interp: $("interp").value }); };

fetch("/api/auth/me").then((r) => {
  if (r.ok) {
    Object.assign($("account"), { href: "/new", textContent: "+ Add record" });
    $("edit").hidden = false;
  }
});

(async () => {
  // /?select=3,7 opens the viewer with these records selected
  const ids = new URLSearchParams(location.search).get("select");
  if (ids && /^[\d,]+$/.test(ids)) {
    const r = await fetch("/api/measurements?ids=" + ids);
    if (r.ok) for (const m of await r.json()) state.selected.set(m.id, m);
  }
  await search();
  draw();
})();
