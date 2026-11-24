"use strict";

const $ = (s) => document.querySelector(s);
const state = { tab: "text", file: null, config: null, previewUrl: null, seq: 0 };

const forms = {
  text: $("#form-text"),
  image: $("#form-image"),
  binsight: $("#form-binsight"),
};

function message(text, kind = "") {
  const m = $("#message");
  m.textContent = text;
  m.className = "message " + kind;
}

async function errorText(res) {
  try {
    const j = await res.json();
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) return j.detail.map((d) => d.msg).join("; ");
    if (j.error) return j.error;
  } catch {}
  return `HTTP ${res.status}`;
}

// ---- what to send for the current tab ----
function request(kind) {
  const size = $("#size").value;
  const copies = Number($("#copies").value) || 1;
  if (state.tab === "text") {
    const f = forms.text;
    const lines = f.lines.value.split("\n").map((l) => l.trimEnd());
    while (lines.length && !lines[lines.length - 1]) lines.pop();
    const qr = f.qr.value.trim();
    if (!lines.length && !qr) return null;
    return json(`/api/${kind}/text`, { lines: lines.length ? lines : [""], qr: qr || null, size, copies, source: "web" });
  }
  if (state.tab === "image") {
    if (!state.file) return null;
    const f = forms.image;
    const q = new URLSearchParams({ size, copies, fit: f.fit.value, rotate: f.rotate.value, dither: f.dither.checked, source: "web" });
    return { url: `/api/${kind}/image?${q}`, init: { method: "POST", headers: { "Content-Type": state.file.type || "application/octet-stream" }, body: state.file } };
  }
  const code = forms.binsight.code.value.trim();
  if (!code) return null;
  return json(`/api/${kind}/binsight`, { code, size, copies, source: "web" });
}

function json(url, body) {
  return { url, init: { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } };
}

// ---- preview ----
let timer;
function schedulePreview(delay = 250) {
  clearTimeout(timer);
  timer = setTimeout(preview, delay);
}

async function preview() {
  const req = request("preview");
  $("#print").disabled = !req;
  if (!req) return showPreview(null);
  const seq = ++state.seq;
  try {
    const res = await fetch(req.url, req.init);
    if (seq !== state.seq) return;
    if (!res.ok) {
      showPreview(null);
      $("#print").disabled = true;
      return message(await errorText(res), "bad");
    }
    showPreview(await res.blob());
    message("");
  } catch (e) {
    if (seq === state.seq) message("Can't reach the print server", "bad");
  }
}

function showPreview(blob) {
  const img = $("#preview");
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = null;
  if (!blob) return img.removeAttribute("src");
  state.previewUrl = URL.createObjectURL(blob);
  img.src = state.previewUrl;
}

// ---- print ----
async function print() {
  const req = request("print");
  if (!req) return;
  const btn = $("#print");
  btn.disabled = true;
  message("Printing…");
  try {
    const res = await fetch(req.url + (req.url.includes("?") ? "&" : "?") + "wait=true", req.init);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) message(body.error ? `Printer: ${body.error}` : await errorTextFrom(body, res), "bad");
    else message(body.status === "done" ? "Printed" : "Queued", "ok");
  } catch {
    message("Can't reach the print server", "bad");
  }
  btn.disabled = false;
  loadJobs();
  loadStatus();
}

async function errorTextFrom(body, res) {
  if (typeof body.detail === "string") return body.detail;
  return `HTTP ${res.status}`;
}

// ---- status and history ----
async function loadStatus() {
  const chip = $("#status");
  try {
    const s = await (await fetch("/api/status")).json();
    if (s.transport === "file") {
      chip.textContent = "No printer (test mode)";
      chip.className = "chip idle";
    } else if (s.last_error) {
      chip.textContent = "Printer error";
      chip.title = s.last_error;
      chip.className = "chip bad";
    } else {
      chip.textContent = s.connected ? "Printer connected" : "Printer ready";
      chip.title = s.address || "";
      chip.className = "chip ok";
    }
  } catch {
    chip.textContent = "Server unreachable";
    chip.className = "chip bad";
  }
}

function ago(t) {
  const s = Math.round(Date.now() / 1000 - t);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(t * 1000).toLocaleDateString();
}

async function loadJobs() {
  const ul = $("#jobs");
  try {
    const { jobs } = await (await fetch("/api/jobs?limit=15")).json();
    ul.replaceChildren(
      ...(jobs.length ? jobs : [null]).map((j) => {
        const li = document.createElement("li");
        if (!j) {
          li.innerHTML = '<span class="empty">Nothing printed yet</span>';
          return li;
        }
        const img = document.createElement("img");
        img.src = `/api/jobs/${j.id}/preview.png`;
        img.alt = "";
        img.loading = "lazy";
        const mid = document.createElement("div");
        const sum = document.createElement("div");
        sum.className = "sum";
        sum.textContent = j.summary;
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = `${j.size}${j.copies > 1 ? ` ×${j.copies}` : ""} · ${j.source} · ${ago(j.created)}`;
        mid.append(sum, meta);
        const st = document.createElement("span");
        st.className = `st ${j.status}`;
        st.textContent = j.status;
        if (j.error) st.title = j.error;
        li.append(img, mid, st);
        return li;
      }),
    );
  } catch {}
}

// ---- wiring ----
function selectTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.dataset.panel !== tab));
  const sizes = state.config;
  if (sizes) $("#size").value = tab === "binsight" ? sizes.binsight_size : sizes.default_size;
  updateDims();
  message("");
  schedulePreview(0);
}

function updateDims() {
  const c = state.config;
  if (!c) return;
  const s = c.sizes[$("#size").value];
  $("#dims").textContent = s ? `${$("#size").value} in · ${s.mm[0]}×${s.mm[1]} mm · ${s.dots[0]}×${s.dots[1]} dots` : "";
}

function setFile(file) {
  if (!file || !file.type.startsWith("image/")) return message("That isn't an image", "bad");
  state.file = file;
  $("#drop-text").textContent = file.name;
  schedulePreview(0);
}

async function init() {
  state.config = await (await fetch("/api/config")).json();
  $("#size").replaceChildren(
    ...Object.keys(state.config.sizes).map((k) => {
      const o = document.createElement("option");
      o.value = k;
      o.textContent = `${k} in`;
      return o;
    }),
  );
  $("#size").value = state.config.default_size;
  updateDims();
  $('.tabs button[data-tab="binsight"]').hidden = !state.config.binsight;

  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
  Object.values(forms).forEach((f) => {
    f.addEventListener("input", () => schedulePreview());
    f.addEventListener("submit", (e) => { e.preventDefault(); print(); });
  });
  $("#size").addEventListener("change", () => { updateDims(); schedulePreview(0); });
  $("#print").addEventListener("click", print);

  const drop = $("#drop");
  forms.image.file.addEventListener("change", (e) => setFile(e.target.files[0]));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); setFile(e.dataTransfer.files[0]); });
  document.addEventListener("paste", (e) => {
    const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
    if (item) { selectTab("image"); setFile(item.getAsFile()); }
  });

  const hash = new URLSearchParams(location.hash.slice(1));
  if (state.config.binsight && hash.get("binsight")) { forms.binsight.code.value = hash.get("binsight"); selectTab("binsight"); }

  loadStatus();
  loadJobs();
  setInterval(loadStatus, 15000);
  setInterval(loadJobs, 30000);
}

init();
