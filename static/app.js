const state = {
  datasets: [], dataset: null, group: "", offset: 0, limit: 100, total: 0,
  scans: [], scan: null, image: null, view: null, results: [], overlays: new Map(),
  zoom: 1, brightness: 1, contrast: 1, jobTimer: null, studyResults: null,
};

const $ = (id) => document.getElementById(id);
const colours = ["#62e6be", "#6fb8ff", "#ff9d68", "#c8a5ff", "#f071a7", "#ffe066", "#8fe388"];
const boundaryColours = ["#55e6ff", "#ffcf5a", "#ff70b7"];

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try { const body = await response.json(); message = body.detail || message; } catch (_) {}
    throw new Error(message);
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
}

function fmt(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const number = Number(value);
  if (Math.abs(number) > 0 && Math.abs(number) < .001) return number.toExponential(2);
  return number.toFixed(digits);
}

function roleClass(arm) {
  if (arm === "V111") return "recipe";
  if (arm === "V100") return "comparator";
  if (arm === "V000") return "reference";
  return "point";
}

function svgText(x, y, text, anchor = "start", extra = "") {
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" ${extra}>${escapeHtml(text)}</text>`;
}

function numericScale(min, max, left, right) {
  const span = max - min || 1;
  return value => left + (Number(value) - min) * (right - left) / span;
}

function dataTable(headers, rows) {
  return `<table class="data-table"><thead><tr>${headers.map(value => `<th>${escapeHtml(value)}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(value => `<td>${escapeHtml(value)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function dotWhiskerChart(dataset) {
  const width = 430, left = 67, right = 18, top = 18, row = 22, bottom = 29;
  const max = Math.max(...dataset.arms.flatMap(item => item.seeds), 0) * 1.08;
  const x = numericScale(0, max, left, width - right), height = top + dataset.arms.length * row + bottom;
  const ticks = [0, max / 2, max];
  let svg = ticks.map(value => `<line class="grid" x1="${x(value)}" x2="${x(value)}" y1="${top - 5}" y2="${height - bottom}"/>${svgText(x(value), height - 8, fmt(value, 1), "middle")}`).join("");
  dataset.arms.forEach((item, index) => {
    const y = top + index * row + 8, lo = Math.max(0, item.mean - item.sd), hi = item.mean + item.sd;
    svg += svgText(left - 9, y + 3, item.arm, "end");
    svg += `<line class="whisker" x1="${x(lo)}" x2="${x(hi)}" y1="${y}" y2="${y}"/>`;
    item.seeds.forEach((value, seed) => { svg += `<circle class="seed" cx="${x(value)}" cy="${y + (seed - 2) * 1.4}" r="2.2"/>`; });
    svg += `<circle class="${roleClass(item.arm)}" cx="${x(item.mean)}" cy="${y}" r="4"/>`;
  });
  return `<article class="chart-card"><h3>${escapeHtml(dataset.label)}</h3><p class="chart-subtitle">Mean ± seed SD, ${escapeHtml(dataset.unit)} · n=${dataset.arms[0]?.n_units ?? "—"} units</p><svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(dataset.label)} performance by recipe">${svg}</svg>${dataTable(["Recipe", `Mean (${dataset.unit})`, "SD"], dataset.arms.map(item => [item.arm, fmt(item.mean), fmt(item.sd)]))}</article>`;
}

function selectionChart(selection) {
  const rows = [...selection.scores].sort((a, b) => a.score - b.score), width = 900, left = 105, right = 40, top = 15, row = 25, bottom = 30;
  const max = Math.max(...rows.map(item => item.score)) * 1.05, x = numericScale(0, max, left, width - right), height = top + rows.length * row + bottom;
  let svg = `<line class="axis" x1="${left}" x2="${width - right}" y1="${height - bottom}" y2="${height - bottom}"/>`;
  [0, max / 2, max].forEach(value => { svg += `<line class="grid" x1="${x(value)}" x2="${x(value)}" y1="${top}" y2="${height - bottom}"/>${svgText(x(value), height - 8, fmt(value, 1), "middle")}`; });
  rows.forEach((item, index) => {
    const y = top + index * row + 8;
    svg += svgText(left - 10, y + 3, item.arm, "end") + `<line class="whisker" x1="${left}" x2="${x(item.score)}" y1="${y}" y2="${y}"/><circle class="${roleClass(item.arm)}" cx="${x(item.score)}" cy="${y}" r="5"/>${svgText(x(item.score) + 9, y + 3, fmt(item.score, 3))}`;
  });
  return `<h3>Ranked normalised score</h3><p class="chart-subtitle">Lower values indicate better aggregate development-set performance.</p><svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Ranked recipe-selection scores">${svg}</svg>`;
}

function forestChart(dataset) {
  const values = dataset.effects.flatMap(item => [item.hierarchical_ci95[0], item.hierarchical_ci95[1], item.effect]);
  const bound = Math.max(...values.map(Math.abs), .1) * 1.12, width = 455, left = 148, right = 18, top = 15, row = 28, bottom = 31;
  const x = numericScale(-bound, bound, left, width - right), height = top + dataset.effects.length * row + bottom;
  let svg = `<line class="zero" x1="${x(0)}" x2="${x(0)}" y1="${top - 5}" y2="${height - bottom}"/>`;
  [-bound, 0, bound].forEach(value => { svg += svgText(x(value), height - 8, fmt(value, 1), "middle"); });
  dataset.effects.forEach((item, index) => {
    const y = top + index * row + 8;
    svg += svgText(left - 8, y + 3, item.label, "end") + `<line class="whisker" x1="${x(item.hierarchical_ci95[0])}" x2="${x(item.hierarchical_ci95[1])}" y1="${y}" y2="${y}"/><circle class="point" cx="${x(item.effect)}" cy="${y}" r="4"/>`;
  });
  return `<article class="chart-card"><h3>${escapeHtml(dataset.label)}</h3><p class="chart-subtitle">Effect on error (${escapeHtml(dataset.unit)}); left of zero favours the factor.</p><svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(dataset.label)} factorial effects">${svg}</svg>${dataTable(["Contrast", "Effect", "Hierarchical 95% interval"], dataset.effects.map(item => [item.label, fmt(item.effect), `${fmt(item.hierarchical_ci95[0])} to ${fmt(item.hierarchical_ci95[1])}`]))}</article>`;
}

function absoluteChart(dataset) {
  const width = 430, left = 80, right = 20, top = 18, row = 47, bottom = 28;
  const max = Math.max(...dataset.absolute.flatMap(item => item.seeds), 0) * 1.08, x = numericScale(0, max, left, width - right), height = top + dataset.absolute.length * row + bottom;
  let svg = "";
  [0, max / 2, max].forEach(value => { svg += `<line class="grid" x1="${x(value)}" x2="${x(value)}" y1="${top}" y2="${height - bottom}"/>${svgText(x(value), height - 7, fmt(value, 1), "middle")}`; });
  dataset.absolute.forEach((item, index) => {
    const y = top + index * row + 14;
    svg += svgText(left - 10, y + 4, item.arm, "end");
    item.seeds.forEach((value, seed) => { svg += `<circle class="seed" cx="${x(value)}" cy="${y + (seed - 2) * 3}" r="3"/>`; });
    svg += `<circle class="${roleClass(item.arm)}" cx="${x(item.mean)}" cy="${y}" r="6"/>${svgText(x(item.mean) + 9, y + 4, fmt(item.mean))}`;
  });
  return `<article class="chart-card"><h3>${escapeHtml(dataset.label)}</h3><p class="chart-subtitle">Absolute unit-macro error; five seed points and pooled mean (${dataset.unit}).</p><svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(dataset.label)} confirmatory absolute performance">${svg}</svg>${dataTable(["Arm", `Mean (${dataset.unit})`], dataset.absolute.map(item => [item.arm, fmt(item.mean)]))}</article>`;
}

function contrastChart(dataset, margin) {
  const values = dataset.contrasts.flatMap(item => item.ci95), min = Math.min(...values, -margin, 0), max = Math.max(...values, margin, 0);
  const pad = (max - min) * .1 || 1, width = 430, left = 100, right = 20, top = 25, row = 50, bottom = 32, x = numericScale(min - pad, max + pad, left, width - right), height = top + dataset.contrasts.length * row + bottom;
  let svg = `<line class="zero" x1="${x(0)}" x2="${x(0)}" y1="${top - 12}" y2="${height - bottom}"/><line class="zero" x1="${x(margin)}" x2="${x(margin)}" y1="${top - 12}" y2="${height - bottom}"/>${svgText(x(margin), 10, `NI +${fmt(margin)} µm`, "middle")}`;
  dataset.contrasts.forEach((item, index) => {
    const y = top + index * row + 10;
    svg += svgText(left - 8, y + 3, item.label, "end") + `<line class="whisker" x1="${x(item.ci95[0])}" x2="${x(item.ci95[1])}" y1="${y}" y2="${y}"/><circle class="point" cx="${x(item.difference)}" cy="${y}" r="5"/>${svgText(left, y + 20, `p=${fmt(item.p_one_sided, 4)} · ${item.supported ? "supported" : "not supported"}`)}`;
  });
  return `<article class="chart-card"><h3>${escapeHtml(dataset.label)} contrasts</h3><p class="chart-subtitle">Difference in unit-macro error with frozen hierarchical 95% interval.</p><svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(dataset.label)} confirmatory contrasts">${svg}</svg>${dataTable(["Contrast", "Difference (µm)", "95% interval", "One-sided p"], dataset.contrasts.map(item => [item.label, fmt(item.difference), `${fmt(item.ci95[0])} to ${fmt(item.ci95[1])}`, fmt(item.p_one_sided, 4)]))}</article>`;
}

function boundaryChart(dataset) {
  const boundaries = [["ILM", "ILM"], ["RPE_inner", "Inner RPE"], ["RPE_outer", "Outer RPE/BM"]], width = 430, left = 102, right = 20, top = 24, row = 49, bottom = 30;
  const max = Math.max(...dataset.arms.flatMap(item => Object.values(item.values))) * 1.08, x = numericScale(0, max, left, width - right), height = top + boundaries.length * row + bottom;
  let svg = "";
  [0, max / 2, max].forEach(value => { svg += `<line class="grid" x1="${x(value)}" x2="${x(value)}" y1="${top - 8}" y2="${height - bottom}"/>${svgText(x(value), height - 7, fmt(value, 1), "middle")}`; });
  boundaries.forEach(([key, label], index) => {
    const y = top + index * row + 12; svg += svgText(left - 8, y + 3, label, "end");
    dataset.arms.forEach((arm, armIndex) => { const yy = y + (armIndex - 1) * 8; svg += `<circle class="${roleClass(arm.arm)}" cx="${x(arm.values[key])}" cy="${yy}" r="4"/>${svgText(x(arm.values[key]) + 7, yy + 3, arm.arm)}`; });
  });
  return `<article class="chart-card"><h3>${escapeHtml(dataset.label)}</h3><p class="chart-subtitle">Descriptive mean absolute boundary error (${dataset.unit}).</p><svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(dataset.label)} boundary-specific error">${svg}</svg>${dataTable(["Boundary", ...dataset.arms.map(item => item.arm)], boundaries.map(([key, label]) => [label, ...dataset.arms.map(item => fmt(item.values[key]))]))}</article>`;
}

async function showMode(mode) {
  const isResults = mode === "results";
  $("viewerWorkspace").classList.toggle("hidden", isResults);
  $("studyResultsWorkspace").classList.toggle("hidden", !isResults);
  $("viewerModeButton").classList.toggle("active", !isResults); $("viewerModeButton").setAttribute("aria-pressed", String(!isResults));
  $("resultsModeButton").classList.toggle("active", isResults); $("resultsModeButton").setAttribute("aria-pressed", String(isResults));
  $("settingsButton").classList.toggle("hidden", isResults); $("importButton").classList.toggle("hidden", isResults);
  if (isResults && !state.studyResults) await loadStudyResults();
}

async function loadStudyResults() {
  const data = await api("/api/study-results"); state.studyResults = data;
  $("studyMetric").textContent = data.metric;
  $("studyNotes").innerHTML = data.notes.map(note => `<div class="study-note">${escapeHtml(note)}</div>`).join("");
  $("exploratoryCharts").innerHTML = data.exploratory.map(dotWhiskerChart).join("");
  $("selectionNote").textContent = data.selection.status_note;
  $("selectionChart").innerHTML = selectionChart(data.selection);
  $("factorialCharts").innerHTML = data.factorial.map(forestChart).join("");
  $("confirmatoryNote").textContent = data.confirmatory.status_note;
  $("confirmatoryCharts").innerHTML = data.confirmatory.datasets.map(absoluteChart).join("");
  $("contrastCharts").innerHTML = data.confirmatory.datasets.map(item => contrastChart(item, data.confirmatory.margin_um)).join("");
  $("boundaryCharts").innerHTML = data.confirmatory.boundaries.map(boundaryChart).join("");
  $("downloadList").innerHTML = data.downloads.map(item => `<a class="download-item" href="/api/study-results/download/${encodeURIComponent(item.id)}"><span>${escapeHtml(item.label)}</span><small>${escapeHtml(item.path)} · ${item.bytes.toLocaleString()} B</small><small>SHA-256 ${escapeHtml(item.sha256.slice(0, 20))}…</small></a>`).join("");
}

async function initialise() {
  const status = await api("/api/status");
  $("registryStatus").textContent = `${status.models}/${status.models_registered} models · ${status.predictions}/${status.predictions_registered} supplied results`;
  $("researchNotice").textContent = status.assets_complete ? status.notice : `${status.notice} Large release assets are incomplete; run scripts/install_release_assets.py (Zenodo ${status.asset_doi}).`;
  const payload = await api("/api/datasets");
  state.datasets = payload.datasets;
  renderDatasets();
  const first = state.datasets.find(item => item.installed);
  if (first) selectDataset(first.dataset);
}

function renderDatasets() {
  $("datasetList").innerHTML = state.datasets.map(item => `
    <button class="dataset-button ${state.dataset === item.dataset ? "active" : ""}" data-dataset="${item.dataset}">
      <strong>${escapeHtml(item.name)}</strong><i class="dot ${item.installed ? "" : "off"}"></i>
      <small>${item.scan_count.toLocaleString()} scans · ${item.read_only ? "read-only" : "local"}</small>
    </button>`).join("");
  document.querySelectorAll(".dataset-button").forEach(button => button.addEventListener("click", () => selectDataset(button.dataset.dataset)));
}

async function selectDataset(dataset) {
  state.dataset = dataset; state.group = ""; state.offset = 0; state.scan = null; state.overlays.clear();
  renderDatasets(); clearViewer();
  const payload = await api(`/api/datasets/${dataset}/groups`);
  $("groupSelect").innerHTML = `<option value="">All groups</option>` + payload.groups.map(item => `<option value="${escapeHtml(item.group)}">${escapeHtml(item.group)} (${item.count})</option>`).join("");
  await loadScans();
}

async function loadScans() {
  const params = new URLSearchParams({offset: state.offset, limit: state.limit});
  if (state.group) params.set("group", state.group);
  if ($("scanSearch").value.trim()) params.set("search", $("scanSearch").value.trim());
  const payload = await api(`/api/datasets/${state.dataset}/scans?${params}`);
  state.scans = payload.scans; state.total = payload.total;
  $("scanSummary").textContent = `${payload.total.toLocaleString()} matching scans`;
  $("pageLabel").textContent = payload.total ? `${payload.offset + 1}–${Math.min(payload.offset + payload.limit, payload.total)} of ${payload.total}` : "0";
  $("previousPage").disabled = state.offset === 0;
  $("nextPage").disabled = state.offset + state.limit >= state.total;
  $("scanList").innerHTML = state.scans.length ? state.scans.map(scan => `
    <button class="scan-card ${state.scan?.scan_id === scan.scan_id ? "active" : ""}" data-scan="${scan.scan_id}">
      <strong>${escapeHtml(scan.label)} <span>${escapeHtml(scan.scan_id)}</span></strong>
      <span>${escapeHtml(scan.group)} · ${escapeHtml(scan.parent)} · ${scan.width}×${scan.height}${scan.views.length ? ` · ${scan.views.length} view(s)` : " · no supplied result"}</span>
    </button>`).join("") : `<p class="empty">No scans match.</p>`;
  document.querySelectorAll(".scan-card").forEach(button => button.addEventListener("click", () => selectScan(button.dataset.scan)));
}

async function selectScan(scanId) {
  state.scan = await api(`/api/scans/${scanId}`); state.overlays.clear();
  renderScanMeta(); renderActiveOverlays(); await loadImage(); await loadResults(); await loadScans();
}

function renderScanMeta() {
  const s = state.scan;
  const spacing = s.axial_um == null ? "axial spacing unknown" : `${s.axial_um.toFixed(4).replace(/0+$/, "").replace(/\.$/, "")} µm/px axial`;
  $("scanMeta").classList.remove("empty");
  $("scanMeta").innerHTML = `<strong>${escapeHtml(s.label)}</strong>${escapeHtml(s.dataset)} · ${s.width}×${s.height} · ${spacing} · ${escapeHtml(s.scan_id)}`;
  $("addCustomButton").disabled = !s.read_only;
  $("addCustomButton").classList.toggle("hidden", !s.read_only);
  $("trashCustomButton").classList.toggle("hidden", s.read_only);
  $("exportButton").disabled = false;
  $("customInference").classList.toggle("hidden", s.dataset !== "custom");
  const warning = s.development_warning ? `Development-data warning: ${s.development_warning.replaceAll("_", " ")}.` : "";
  $("scanWarning").textContent = warning;
  $("scanWarning").classList.toggle("hidden", !warning);
}

async function loadImage() {
  const image = new Image();
  image.onload = () => { state.image = image; $("canvasEmpty").classList.add("hidden"); draw(); };
  image.onerror = () => showWarning("The B-scan could not be loaded.");
  image.src = `/api/scans/${state.scan.scan_id}/image?cache=${Date.now()}`;
}

async function loadResults() {
  const preliminary = await api(`/api/scans/${state.scan.scan_id}/results`);
  const views = preliminary.views || ["custom"];
  $("viewSelect").disabled = views.length === 0;
  $("viewSelect").innerHTML = views.length ? views.map(view => `<option value="${view}">${viewLabel(view)}</option>`).join("") : `<option>No supplied view</option>`;
  state.view = preliminary.view || views[0] || null;
  if (state.view) $("viewSelect").value = state.view;
  const payload = state.view ? await api(`/api/scans/${state.scan.scan_id}/results?view=${encodeURIComponent(state.view)}`) : preliminary;
  state.results = payload.results || [];
  if (payload.warning) showWarning(payload.warning);
  renderResults();
}

function viewLabel(view) {
  const names = {all41:"OCT5K manual AMD/healthy", dme:"DME", aroi__ax1:"AROI AX1", aroi__ax2:"AROI AX2 control", aroi__ax3:"AROI AX3 control", aroi__ax4:"AROI AX4 control", jhu:"JHU", custom:"Custom"};
  return names[view] || view;
}

function renderResults() {
  const family = $("familyFilter").value, arm = $("armFilter").value.trim().toLowerCase(), seed = $("seedFilter").value;
  const filtered = state.results.filter(item => (!family || item.category === family) && (!arm || item.arm.toLowerCase().includes(arm)) && (seed === "" || String(item.seed) === seed));
  $("availabilityText").textContent = `${state.results.length} available for ${state.view ? viewLabel(state.view) : "this scan"}`;
  $("resultList").innerHTML = filtered.length ? filtered.map((item, index) => `
    <button class="result-card" data-result="${item.result_id}">
      <i class="swatch" style="background:${colours[index % colours.length]}"></i>
      <span><strong>${escapeHtml(item.arm)} · seed ${item.seed}${item.role ? ` · ${item.role}` : ""}</strong><span>${escapeHtml(item.adaptation || factorLabel(item))}</span></span>
      <span class="tier">${escapeHtml(item.tier.replaceAll("_", " "))}</span>
    </button>`).join("") : `<p class="empty">No results match the filters.</p>`;
  document.querySelectorAll(".result-card").forEach(button => button.addEventListener("click", () => togglePrediction(button.dataset.result)));
  const arms = [...new Set(state.results.map(item => item.arm))].sort();
  $("averageArm").innerHTML = `<option value="">Choose recipe/method</option>` + arms.map(value => `<option>${value}</option>`).join("");
  $("averageButton").disabled = !state.scan || arms.length === 0;
}

function factorLabel(item) {
  if (item.category !== "factorial") return item.category;
  const active = [item.scale && "scale", item.occlusion && "occlusion", item.fda && "FDA"].filter(Boolean);
  return active.length ? active.join(" + ") : "unadapted reference";
}

async function togglePrediction(resultId) {
  if (state.overlays.has(resultId)) { state.overlays.delete(resultId); draw(); renderActiveOverlays(); return; }
  if (state.overlays.size >= 6) { showWarning("Remove an overlay before adding another; the display limit is six."); return; }
  const prediction = await api(`/api/scans/${state.scan.scan_id}/predictions/${encodeURIComponent(resultId)}`);
  state.overlays.set(resultId, prediction); draw(); renderActiveOverlays();
}

async function addAverage() {
  const arm = $("averageArm").value; if (!arm) return;
  const key = `average::${arm}::${state.view}`;
  if (state.overlays.has(key)) { state.overlays.delete(key); draw(); renderActiveOverlays(); return; }
  try {
    const prediction = await api(`/api/scans/${state.scan.scan_id}/seed-average/${arm}?view=${encodeURIComponent(state.view)}`);
    prediction.result_id = key; prediction.arm = `${arm} average`; state.overlays.set(key, prediction); draw(); renderActiveOverlays();
  } catch (error) { showWarning(error.message); }
}

function draw() {
  if (!state.image) return;
  const canvas = $("octCanvas"), ctx = canvas.getContext("2d");
  const baseScale = Math.min(900 / state.image.naturalWidth, 560 / state.image.naturalHeight);
  const scale = baseScale * state.zoom;
  canvas.width = Math.max(1, Math.round(state.image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(state.image.naturalHeight * scale));
  ctx.filter = `brightness(${state.brightness}) contrast(${state.contrast})`;
  ctx.drawImage(state.image, 0, 0, canvas.width, canvas.height);
  ctx.filter = "none"; ctx.lineJoin = "round"; ctx.lineCap = "round";
  [...state.overlays.values()].forEach((overlay, overlayIndex) => {
    overlay.mean_px.forEach((curve, boundary) => {
      ctx.beginPath(); ctx.strokeStyle = boundaryColours[boundary]; ctx.lineWidth = overlayIndex === 0 ? 1.8 : 1.15; ctx.globalAlpha = Math.max(.45, 1 - overlayIndex * .09);
      curve.forEach((row, x) => {
        const px = (x + .5) * scale, py = (row + .5) * scale;
        if (x === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      });
      ctx.stroke();
    });
  });
  ctx.globalAlpha = 1;
}

function renderActiveOverlays() {
  $("activeOverlayList").innerHTML = state.overlays.size ? [...state.overlays.entries()].map(([key, value]) => `<span class="overlay-chip">${escapeHtml(value.arm || value.model_id || key)}${value.seed == null ? "" : ` s${value.seed}`}<button data-remove="${escapeHtml(key)}" aria-label="Remove overlay">×</button></span>`).join("") : `<span class="small-note">No prediction overlay selected.</span>`;
  document.querySelectorAll("[data-remove]").forEach(button => button.addEventListener("click", () => { state.overlays.delete(button.dataset.remove); draw(); renderActiveOverlays(); }));
}

function clearViewer() {
  state.image = null; state.results = []; state.overlays.clear();
  const canvas = $("octCanvas"); canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  $("canvasEmpty").classList.remove("hidden"); $("scanMeta").textContent = "Select a scan from the browser."; $("scanMeta").classList.add("empty");
  $("resultList").innerHTML = `<p class="empty">No results loaded.</p>`; $("availabilityText").textContent = "Select a scan.";
  $("addCustomButton").disabled = true; $("exportButton").disabled = true; $("customInference").classList.add("hidden");
  $("trashCustomButton").classList.add("hidden");
}

function showWarning(message) { $("scanWarning").textContent = message; $("scanWarning").classList.remove("hidden"); }

async function addCurrentToCustom() {
  if (!state.scan || !confirm("Confirm that the displayed scan has vitreous at the top, deeper tissue below, and no unexpected rotation or burned-in identity text.")) return;
  try {
    const payload = await api(`/api/scans/${state.scan.scan_id}/add-to-custom`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({orientation_confirmed:true})});
    alert(payload.created ? `Created ${payload.scan.label}` : `This scan already exists as ${payload.scan.label}.`);
    await refreshDatasets(); selectDataset("custom");
  } catch (error) { showWarning(error.message); }
}

async function refreshDatasets() { state.datasets = (await api("/api/datasets")).datasets; renderDatasets(); }

async function submitImport(event) {
  event.preventDefault(); const form = new FormData(event.target);
  try {
    const response = await fetch("/api/custom/import", {method:"POST", body:form});
    if (!response.ok) { const body = await response.json(); throw new Error(body.detail || response.statusText); }
    const payload = await response.json(); $("importDialog").close(); event.target.reset(); await refreshDatasets(); await selectDataset("custom");
    alert(payload.created ? `Created ${payload.scan.label}` : `This scan already exists as ${payload.scan.label}.`);
  } catch (error) { $("importError").textContent = error.message; $("importError").classList.remove("hidden"); }
}

async function previewCustomFile() {
  const file = $("customFile").files[0];
  if (!file) { $("customPreviewBox").classList.add("hidden"); return; }
  const form = new FormData(); form.append("file", file); form.append("confirm_16bit", $("importForm").elements.namedItem("confirm_16bit").checked ? "true" : "false");
  try {
    const response = await fetch("/api/custom/preview", {method:"POST", body:form});
    if (!response.ok) { const body = await response.json(); throw new Error(body.detail || response.statusText); }
    const blob = await response.blob(), url = URL.createObjectURL(blob);
    $("customPreview").onload = () => URL.revokeObjectURL(url);
    $("customPreview").src = url; $("customPreviewBox").classList.remove("hidden");
    $("importError").classList.add("hidden");
  } catch (error) {
    $("customPreviewBox").classList.add("hidden"); $("importError").textContent = error.message; $("importError").classList.remove("hidden");
  }
}

async function trashCurrentCustom() {
  if (!state.scan || state.scan.dataset !== "custom") return;
  if (!confirm(`Move ${state.scan.label} and all of its generated results to the application trash?`)) return;
  try {
    await api(`/api/custom/${state.scan.scan_id}`, {method:"DELETE"});
    state.scan = null; clearViewer(); await refreshDatasets(); await selectDataset("custom");
  } catch (error) { showWarning(error.message); }
}

async function openSettings() {
  const payload = await api("/api/settings/dataset-roots");
  Object.entries(payload.dataset_roots).forEach(([key, value]) => { const field = $("settingsForm").elements.namedItem(key); if (field) field.value = value; });
  $("settingsDialog").showModal();
}

async function saveSettings(event) {
  event.preventDefault();
  const form = new FormData(event.target), dataset_roots = {};
  ["oct5k_annotations","oct5k_raw","aroi","duke_amd","jhu","duke_dme"].forEach(key => dataset_roots[key] = form.get(key));
  try {
    await api("/api/settings/dataset-roots", {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify({dataset_roots})});
    $("settingsDialog").close(); await refreshDatasets(); if (state.dataset) await selectDataset(state.dataset);
  } catch (error) { $("settingsError").textContent = error.message; $("settingsError").classList.remove("hidden"); }
}

async function runAllModels() {
  if (!state.scan || state.scan.dataset !== "custom") return;
  if (!confirm("Run all installed models on this Custom scan? Results are research-only exploratory output.")) return;
  try {
    const job = await api(`/api/custom/${state.scan.scan_id}/inference`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({device:$("deviceSelect").value})});
    pollJob(job.job_id);
  } catch (error) { showWarning(error.message); }
}

function pollJob(jobId) {
  clearInterval(state.jobTimer);
  state.jobTimer = setInterval(async () => {
    try {
      const job = await api(`/api/jobs/${jobId}`);
      $("jobStatus").textContent = `${job.state}: ${job.completed}/${job.model_ids.length}${job.current_model ? ` · ${job.current_model}` : ""}`;
      if (job.state.startsWith("completed")) { clearInterval(state.jobTimer); await loadResults(); }
    } catch (error) { clearInterval(state.jobTimer); showWarning(error.message); }
  }, 1000);
}

function exportFigure() {
  if (!state.scan) return;
  if (!confirm("The exported figure contains locally installed dataset pixels. You are responsible for the source dataset's terms. Continue?")) return;
  const link = document.createElement("a"); link.download = `${state.scan.scan_id}_viewer.png`; link.href = $("octCanvas").toDataURL("image/png"); link.click();
  const provenance = {scan_id:state.scan.scan_id, view:state.view, exported_utc:new Date().toISOString(), pixel_convention:"canvas x+0.5,y+0.5", overlays:[...state.overlays.values()].map(value => ({result_id:value.result_id, model_id:value.model_id, arm:value.arm, seed:value.seed, derived_rule:value.derived_rule, source_result_ids:value.source_result_ids}))};
  const blob = new Blob([JSON.stringify(provenance, null, 2)], {type:"application/json"});
  const sidecar = document.createElement("a"); sidecar.download = `${state.scan.scan_id}_viewer.provenance.json`; sidecar.href = URL.createObjectURL(blob); sidecar.click(); setTimeout(() => URL.revokeObjectURL(sidecar.href), 1000);
}

$("groupSelect").addEventListener("change", event => { state.group = event.target.value; state.offset = 0; loadScans(); });
let searchTimer; $("scanSearch").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.offset = 0; loadScans(); }, 250); });
$("previousPage").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); loadScans(); });
$("nextPage").addEventListener("click", () => { state.offset += state.limit; loadScans(); });
$("viewSelect").addEventListener("change", async event => { state.view = event.target.value; state.overlays.clear(); renderActiveOverlays(); draw(); const payload = await api(`/api/scans/${state.scan.scan_id}/results?view=${encodeURIComponent(state.view)}`); state.results = payload.results; renderResults(); });
[$("familyFilter"), $("armFilter"), $("seedFilter")].forEach(control => control.addEventListener("input", renderResults));
$("averageButton").addEventListener("click", addAverage);
$("addCustomButton").addEventListener("click", addCurrentToCustom);
$("trashCustomButton").addEventListener("click", trashCurrentCustom);
$("exportButton").addEventListener("click", exportFigure);
$("importButton").addEventListener("click", () => $("importDialog").showModal());
$("closeImport").addEventListener("click", () => $("importDialog").close());
$("cancelImport").addEventListener("click", () => $("importDialog").close());
$("importForm").addEventListener("submit", submitImport);
$("customFile").addEventListener("change", previewCustomFile);
$("importForm").elements.namedItem("confirm_16bit").addEventListener("change", previewCustomFile);
$("settingsButton").addEventListener("click", openSettings);
$("closeSettings").addEventListener("click", () => $("settingsDialog").close());
$("cancelSettings").addEventListener("click", () => $("settingsDialog").close());
$("settingsForm").addEventListener("submit", saveSettings);
$("runAllButton").addEventListener("click", runAllModels);
$("viewerModeButton").addEventListener("click", () => showMode("viewer"));
$("resultsModeButton").addEventListener("click", () => showMode("results").catch(error => { $("researchNotice").textContent = error.message; }));
[["zoomControl","zoomValue","zoom"],["brightnessControl","brightnessValue","brightness"],["contrastControl","contrastValue","contrast"]].forEach(([controlId,valueId,key]) => $(controlId).addEventListener("input", event => { state[key] = Number(event.target.value)/100; $(valueId).textContent = `${event.target.value}%`; draw(); }));

initialise().catch(error => { $("researchNotice").textContent = error.message; $("researchNotice").style.background = "#4a1717"; });

