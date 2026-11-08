// Staff page: login, poll /api/staff/overview every 2 s, render, actions.
"use strict";

const $ = (id) => document.getElementById(id);
let token = sessionStorage.getItem("staffToken") || "";
if (location.hash.startsWith("#token=")) {          // hand-over from another device / tests
  token = decodeURIComponent(location.hash.slice(7)); sessionStorage.setItem("staffToken", token);
  history.replaceState(null, "", location.pathname);
}
let data = null;

const PRINTER = {
  offline: ["Drucker offline", "bad"], idle: ["Drucker bereit", "ok"], printing: ["Druckt", "busy"],
  attention: ["Drucker wartet", "att"], paused: ["Pausiert", "att"], finished: ["Fertig", "ok"],
  busy: ["Beschäftigt", "busy"], error: ["Fehler", "bad"],
};
const TAG_STATUS = { held: "wartet auf Zahlung", queued: "in Warteschlange", plated: "wird gedruckt",
  printed: "fertig", cancelled: "storniert" };
const SHAPE = { stadium: "Anhänger", star: "Stern", tree: "Baum", bell: "Glocke" };

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const color = (id) => data.text_colors.find((c) => c.id === id) || { name: id, hex: "#888" };
const dot = (hex) => `<span class="dot" style="background:${esc(hex)}"></span>`;
const euro = (cents) => (cents / 100).toFixed(2).replace(".", ",") + " €";
const mins = (s) => (s == null ? "–" : Math.max(0, Math.round(s / 60)) + " min");

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { "X-Staff-Token": token, "Content-Type": "application/json" } });
  if (r.status === 401) { showLogin(); throw new Error("login"); }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.message || body.detail || r.status);
  return body;
}

async function act(path, confirmText) {
  if (confirmText && !confirm(confirmText)) return;
  try { await api(path, { method: "POST" }); await refresh(); }
  catch (e) { if (e.message !== "login") alert("Fehler: " + e.message); }
}

function showLogin() {
  token = ""; sessionStorage.removeItem("staffToken");
  $("app").classList.add("hidden"); $("login").classList.remove("hidden"); $("pin").focus();
}

async function login() {
  const r = await fetch("/api/staff/login", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin: $("pin").value }) });
  if (!r.ok) { $("loginErr").textContent = "Falsche PIN"; return; }
  token = (await r.json()).token; sessionStorage.setItem("staffToken", token);
  $("login").classList.add("hidden"); $("app").classList.remove("hidden"); $("pin").value = "";
  refresh();
}

function plateMap(p) {
  const W = 250, H = 220;
  const nums = Object.fromEntries(p.tags.map((t) => [t.id, t]));
  const rects = p.map.map((m) => {
    const t = nums[m.tag_id] || { name: "?", order_number: "?" };
    const y = H - m.y - m.h;                       // printer Y=0 is the front -> bottom of the drawing
    const rect = `<rect x="${m.x}" y="${y}" width="${m.w}" height="${m.h}" rx="3" fill="${esc(data.base_color.hex)}"/>`;
    const name = `<tspan fill="${esc(color(p.text_color).hex)}">${esc(t.name)}</tspan>`;
    if (m.h < 26)                                  // flat tag: number and name in one line
      return rect + `<text x="${m.x + 3}" y="${y + m.h / 2 + 3}">#${esc(t.order_number)} ${name}</text>`;
    return rect + `<text class="num" x="${m.x + 3}" y="${y + 12}">#${esc(t.order_number)}</text>
      <text x="${m.x + 3}" y="${y + m.h - 4}">${name}</text>`;
  }).join("");
  return `<svg class="map" viewBox="0 0 ${W} ${H + 12}">
    <rect width="${W}" height="${H}" fill="#3a3a46" rx="4"/>${rects}
    <text x="${W / 2 - 14}" y="${H + 10}">vorne</text></svg>`;
}

function renderPlate() {
  const el = $("plateCard");
  const st = data.printer;
  const active = data.plates.find((p) => ["building", "printing", "color_change", "printed"].includes(p.status));
  const failed = !active && data.plates[0] && data.plates[0].status === "failed" ? data.plates[0] : null;
  const base = data.base_color;
  if (!active) {
    el.innerHTML = `<h2>Aktuelle Platte</h2>` + (failed
      ? `<div class="banner bad">Platte ${failed.id} fehlgeschlagen</div><p class="err">${esc(failed.error || "")}</p>
         <p>Die Namen sind wieder in der Warteschlange. Drucker prüfen, dann oben „Weiter“ drücken.</p>`
      : `<p class="muted">Keine Platte in Arbeit. ${data.paused ? "Warteschlange pausiert." :
          "Nächste Platte startet, wenn genug Namen einer Farbe warten (oder „Jetzt starten“)."}</p>
         <p>Im Drucker muss die Grundfarbe ${dot(base.hex)}<b>${esc(base.name)}</b> eingelegt sein.</p>`);
    return;
  }
  const c = color(active.text_color);
  const names = active.tags.map((t) => `${esc(t.name)} <span class="muted">#${t.order_number}</span>`).join(", ");
  let body = "";
  if (active.status === "building") body = `<div class="banner">Platte wird vorbereitet …</div>`;
  if (active.status === "printing") body = `
    <div class="row">${dot(base.hex)} Grundfarbe ${esc(base.name)}, dann Text ${dot(c.hex)}<b>${esc(c.name)}</b></div>
    <div class="bar"><div style="width:${st.progress}%"></div></div>
    <p class="muted">${st.progress} % · noch ${mins(st.remaining_s)} · geschätzt ${mins(active.est_s)}</p>
    <p>Beim Farbwechsel <b>${esc(c.name)}</b> einlegen.</p>`;
  if (active.status === "color_change") body = `
    <div class="banner att">Farbwechsel! ${dot(c.hex)}${esc(c.name)} einlegen und am Drucker bestätigen</div>
    ${data.printer.kind === "sim" ? `<button class="warn" onclick="act('/api/staff/sim/resume')">Sim: Farbe gewechselt</button>` : ""}`;
  if (active.status === "printed") body = `
    <div class="banner ok">Platte fertig – Anhänger abnehmen und sortieren</div>
    ${plateMap(active)}
    <div class="row"><button class="primary" onclick="act('/api/staff/plates/${active.id}/cleared',
      'Platte leer und Grundfarbe ${esc(base.name)} eingelegt?')">Platte leer &amp; ${esc(base.name)} eingelegt</button></div>`;
  el.innerHTML = `<h2>Platte ${active.id} ${dot(c.hex)}${esc(c.name)} · ${active.tags.length} Anhänger</h2>
    ${body}<p class="muted">${names}</p>
    <div class="row">
      ${active.status !== "printed" && active.map.length ? `<details><summary class="muted">Plattenplan</summary>${plateMap(active)}</details>` : ""}
      ${active.gcode ? `<a class="muted" href="/api/staff/plates/${active.id}/gcode?token=${encodeURIComponent(token)}">G-Code (USB)</a>` : ""}
      <button class="danger small" onclick="act('/api/staff/plates/${active.id}/cancel',
        'Platte abbrechen? Die Namen kommen zurück in die Warteschlange.${data.printer.kind === "prusalink" ? " Der Druck wird am Drucker gestoppt." : " Den Druck am Drucker selbst stoppen!"}')">Abbrechen</button>
    </div>`;
}

function renderWaiting() {
  const w = data.waiting_by_color;
  const rows = data.text_colors.filter((c) => w[c.id]).map((c) => `
    <div class="row">${dot(c.hex)}<b>${esc(c.name)}</b>: ${w[c.id]} Anhänger
      <button class="small" onclick="act('/api/staff/start_now/${c.id}')">Jetzt starten</button></div>`).join("");
  $("waiting").innerHTML = (rows || `<p class="muted">Keine Namen in der Warteschlange.</p>`) +
    (data.held ? `<p class="muted">${data.held} Anhänger warten auf Zahlung.</p>` : "");
}

function renderOrders() {
  const orders = data.orders.slice().sort((a, b) => (b.ready - a.ready) || (a.paid - b.paid) || (a.number - b.number));
  $("orders").innerHTML = orders.map((o) => {
    const due = !o.paid && o.price_cents > 0;
    const tags = o.tags.map((t) => `<div class="tag">${dot(color(t.text_color).hex)}<span class="name">${esc(t.name)}</span>
      <span class="muted">${esc(SHAPE[t.shape] || t.shape)} · ${esc(t.font)} · ${TAG_STATUS[t.status] || t.status}${t.free ? " · gratis" : ""}</span>
      ${["held", "queued"].includes(t.status) ? `<button class="danger small" onclick="act('/api/staff/tags/${t.id}/cancel', 'Anhänger ${esc(t.name)} stornieren?')">✕</button>` : ""}
      </div>`).join("");
    return `<div class="order"><div class="row"><span class="num">#${o.number}</span>
      ${o.customer ? `<b class="customer">${esc(o.customer)}</b>` : ""}
      ${o.day !== data.today ? `<span class="chip">${esc(o.day.slice(8))}.${esc(o.day.slice(5, 7))}.</span>` : ""}
      ${o.ready ? `<span class="chip ok">abholbereit</span>` : ""}
      ${due ? `<span class="chip att">${euro(o.price_cents)} offen</span>
        <button class="warn small" onclick="act('/api/staff/orders/${o.id}/paid', '${euro(o.price_cents)} kassiert?')">Bezahlt</button>` : ""}
      ${o.ready ? `<button class="primary small" onclick="act('/api/staff/orders/${o.id}/handed_out')">Abgeholt</button>` : ""}
      <button class="danger small" onclick="act('/api/staff/orders/${o.id}/cancel', 'Bestellung #${o.number}${o.customer ? ` (${esc(o.customer)})` : ""} stornieren?')">Storno</button>
      </div>${tags}</div>`;
  }).join("") || `<p class="muted">Keine offenen Bestellungen.</p>`;
}

function renderPlates() {
  const label = { building: "wird gebaut", printing: "druckt", color_change: "Farbwechsel", printed: "fertig, abnehmen",
    done: "erledigt", failed: "fehlgeschlagen", cancelled: "abgebrochen" };
  $("plates").innerHTML = data.plates.map((p) => `<div class="row">Platte ${p.id} ${dot(color(p.text_color).hex)}
    ${p.tags.length} Anhänger · ${label[p.status] || p.status} ${p.est_s ? "· " + mins(p.est_s) : ""}
    ${p.error ? `<span class="err">${esc(p.error)}</span>` : ""}</div>`).join("") || `<p class="muted">Noch keine.</p>`;
}

function render() {
  const [txt, cls] = PRINTER[data.printer.state] || [data.printer.state, ""];
  $("printerChip").textContent = txt + (data.printer.kind === "sim" ? " (Sim)" : "");
  $("printerChip").className = "chip " + cls;
  $("etaAll").textContent = data.eta_all_s > 0 ? `alles fertig in ca. ${mins(data.eta_all_s)}` : "";
  $("pauseBtn").textContent = data.paused ? "Weiter" : "Pause";
  $("pauseBtn").className = "small " + (data.paused ? "primary" : "");
  $("pauseReason").textContent = data.paused ? "Warteschlange pausiert" + (data.pause_reason ? ": " + data.pause_reason : "") : "";
  $("pauseReason").classList.toggle("hidden", !data.paused);
  renderPlate(); renderWaiting(); renderOrders(); renderPlates();
  renderClock();
}

// The Pi has no internet at the booth: its clock decides pickup numbers and times.
function renderClock() {
  const off = Math.round((data.server_time * 1000 - Date.now()) / 60000);
  const el = $("clockBanner");
  el.classList.toggle("hidden", Math.abs(off) < 3);
  if (Math.abs(off) >= 3) {
    el.innerHTML = `Uhrzeit des Kiosk-Rechners geht ${Math.abs(off)} min ${off > 0 ? "vor" : "nach"}!
      <button class="small" onclick="syncClock()">Uhrzeit vom Handy übernehmen</button>`;
  }
}

async function syncClock() {
  try { await api("/api/staff/system/time", { method: "POST", body: JSON.stringify({ time: Date.now() / 1000 }) }); refresh(); }
  catch (e) { if (e.message !== "login") alert("Geht nur auf dem Kiosk-Pi: " + e.message); }
}

async function refresh() {
  if (!token) return showLogin();
  try { data = await api("/api/staff/overview"); render(); }
  catch (e) { if (e.message !== "login") $("printerChip").textContent = "Server nicht erreichbar"; }
}

$("loginBtn").onclick = login;
$("pin").addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });
$("pauseBtn").onclick = () => act(`/api/staff/pause/${data && data.paused ? 0 : 1}`);
if (token) { $("app").classList.remove("hidden"); refresh(); } else showLogin();
setInterval(refresh, 2000);
