// Staff page: login, poll /api/staff/overview every 2 s, plates + pickup list, actions.
// Used by kids at the booth: big, short words, icons, every risky tap asks first.
"use strict";

const $ = (id) => document.getElementById(id);
let token = sessionStorage.getItem("staffToken") || "";
if (location.hash.startsWith("#token=")) {          // hand-over from another device / tests
  token = decodeURIComponent(location.hash.slice(7)); sessionStorage.setItem("staffToken", token);
  history.replaceState(null, "", location.pathname);
}
let data = null;

// [text, css class, icon]  (settings.js uses the text)
const PRINTER = {
  offline: ["Drucker aus", "bad", "📵"], idle: ["Drucker bereit", "ok", "✅"], printing: ["Druckt", "busy", "🖨️"],
  attention: ["Drucker wartet", "att", "✋"], paused: ["Pause", "att", "⏸️"], finished: ["Fertig", "ok", "✅"],
  busy: ["Beschäftigt", "busy", "⏳"], error: ["Fehler", "bad", "❌"],
};
const PLATE = {                     // plate state -> [icon, word, css]
  waiting: ["⏳", "Wartet", "wait"], printing: ["🖨️", "Druckt", "busy"], done: ["✅", "Fertig", "ok"],
  error: ["❌", "Fehler", "bad"],
};
const TAG_ICON = { held: "⏳", queued: "⏳", plated: "🖨️", printed: "✅", cancelled: "✕" };
const SHAPE = { stadium: "Anhänger", wave: "Welle", star: "Stern", tree: "Baum", bell: "Glocke" };

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

// ---------------------------------------------------------------- big dialogs
let modalYes = null;
function ask(html, yesLabel = "✓ Ja", yesClass = "primary") {
  return new Promise((resolve) => {
    $("modalText").innerHTML = html;
    $("modalYes").textContent = yesLabel;
    $("modalYes").className = "big " + yesClass;
    $("modalYes").classList.remove("hidden");
    $("modalNo").textContent = "✕ Nein";
    $("modal").classList.remove("hidden");
    modalYes = resolve;
  });
}
function tell(html) {                     // message with one OK button
  $("modalText").innerHTML = html;
  $("modalYes").classList.add("hidden");
  $("modalNo").textContent = "OK";
  $("modal").classList.remove("hidden");
  modalYes = null;
}
function closeModal(answer) {
  $("modal").classList.add("hidden");
  if (modalYes) modalYes(answer);
  modalYes = null;
}
$("modalYes").onclick = () => closeModal(true);
$("modalNo").onclick = () => closeModal(false);

async function act(path, question, yesLabel, yesClass) {
  if (question && !(await ask(question, yesLabel, yesClass))) return;
  try { await api(path, { method: "POST" }); await refresh(); }
  catch (e) { if (e.message !== "login") tell(`<p class="q">❌ Geht nicht</p><p>${esc(e.message)}</p>`); }
}

// ---------------------------------------------------------------- login
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

// ---------------------------------------------------------------- plate preview
function bbox(d) {
  const n = (d.match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/gi) || []).map(Number);
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i + 1 < n.length; i += 2) {
    x0 = Math.min(x0, n[i]); x1 = Math.max(x1, n[i]); y0 = Math.min(y0, n[i + 1]); y1 = Math.max(y1, n[i + 1]);
  }
  return [x0, y0, x1, y1];
}

// Bed seen from above, front at the bottom; real tag shapes with the order number.
function plateSvg(p) {
  const W = 250, H = 220;
  const byId = Object.fromEntries(p.tags.map((t) => [t.id, t]));
  const base = data.base_color.hex, txt = color(p.text_color).hex;
  const tags = p.map.map((m) => {
    const t = byId[m.tag_id];
    if (!t) return "";
    const top = H - m.y - m.h;                      // printer Y=0 is the front -> bottom of the drawing
    let shape;
    if (t.outline) {
      const [x0, y0] = bbox(t.outline);
      shape = `<g transform="translate(${m.x - x0} ${top - y0})">
        <path d="${t.outline}" fill="${esc(base)}" fill-rule="evenodd" stroke="rgba(0,0,0,.4)" stroke-width=".4"/>
        <path d="${t.text}" fill="${esc(txt)}" fill-rule="evenodd"/></g>`;
    } else {
      shape = `<rect x="${m.x}" y="${top}" width="${m.w}" height="${m.h}" rx="3" fill="${esc(base)}"/>
        <text class="name" x="${m.x + m.w / 2}" y="${top + m.h / 2 + 3}" fill="${esc(txt)}">${esc(t.name)}</text>`;
    }
    return shape + `<g class="badge"><rect x="${m.x - 4}" y="${top - 6}" width="${String(t.order_number).length * 5 + 9}"
      height="10" rx="5"/><text x="${m.x + 0.5}" y="${top + 1.6}">#${esc(t.order_number)}</text></g>`;
  }).join("");
  return `<svg class="bed" viewBox="-8 -10 ${W + 16} ${H + 26}">
    <rect width="${W}" height="${H}" rx="6" fill="#3a3a46"/>${tags}
    <text class="front" x="${W / 2}" y="${H + 12}">▼ vorne ▼</text></svg>`;
}

function showPreview(id) {
  const p = data.plates.find((x) => x.id === id);
  if (!p) return;
  const c = color(p.text_color);
  $("preview").innerHTML = `<div class="preview-title">Platte ${p.id} · ${dot(c.hex)} ${esc(c.name)} ·
    ${p.count} von ${p.max} <span class="muted">· tippen zum Schließen</span></div>${plateSvg(p)}`;
  $("preview").classList.remove("hidden");
}
$("preview").onclick = () => $("preview").classList.add("hidden");

// ---------------------------------------------------------------- plates
const busy = () => data.plates.some((p) => p.state === "printing");

function plateRow(p) {
  const [icon, word, cls] = PLATE[p.state];
  const c = color(p.text_color);
  const st = data.printer;
  let extra = "";
  if (p.status === "building") extra = `<div class="note">⚙️ Wird vorbereitet …</div>`;
  if (p.status === "printing") {
    const prog = st.progress || 0;
    extra = `<div class="bar"><div style="width:${prog}%"></div></div>
      <div class="note">${Math.round(prog)} % · noch ${mins(st.remaining_s)}</div>`;
  }
  if (p.status === "color_change") extra = `<div class="banner att">🎨 Jetzt ${dot(c.hex)} ${esc(c.name)} einlegen!</div>
    ${st.kind === "sim" ? `<button class="warn" data-sim>Sim: Farbe gewechselt</button>` : ""}`;
  if (p.state === "error") extra = `<div class="note err">${esc(p.error || "Fehler")}</div>`;
  if (p.state === "done") extra = `<div class="note">🧹 Anhänger abnehmen</div>`;

  let btn = "";
  if (p.state === "waiting" || p.state === "error" || p.state === "done") {
    const label = p.state === "waiting" ? "▶ Start" : "🔁 Nochmal";
    btn = `<button class="big ${p.state === "waiting" ? "primary" : "warn"}" data-start="${p.id}"
      ${busy() ? "disabled" : ""}>${label}</button>`;
  }
  const names = p.tags.map((t) => `${esc(t.name)} <span class="muted">#${esc(t.order_number)}</span>`).join(", ");
  return `<div class="plate ${cls}${p.recommended && !busy() ? " next" : ""}" data-show="${p.id}">
    <div class="plate-main">
      <span class="pstate ${cls}">${icon} ${word}</span>
      <span class="pnum">Platte ${p.id}</span>
      <span class="pcolor">${dot(c.hex)} ${esc(c.name)}</span>
      <span class="pcount">🏷️ ${p.count}/${p.max}</span>
      ${p.recommended && !busy() ? `<span class="hint">⭐ als Nächstes</span>` : ""}
      <span class="spacer"></span>
      ${btn}
      <button class="big icon danger" data-del="${p.id}" title="Löschen">🗑️</button>
    </div>
    ${extra}
    <div class="names">${names} <span class="eye">👁️</span></div>
  </div>`;
}

function renderPlates() {
  $("plates").innerHTML = data.plates.map(plateRow).join("") ||
    `<p class="empty">Noch keine Platten. Sie kommen, sobald jemand bestellt.</p>`;
}

function startPlate(p) {
  const c = color(p.text_color), base = data.base_color;
  const again = p.state !== "waiting";
  act(`/api/staff/plates/${p.id}/start`, `<p class="q">${again ? "🔁" : "▶"} Platte ${p.id} ${again ? "nochmal drucken" : "starten"}?</p>
    <ul class="checks"><li>🧹 Druckplatte leer?</li><li>${dot(base.hex)} <b>${esc(base.name)}</b> eingelegt?</li></ul>
    <p class="muted">Danach Text in ${dot(c.hex)} ${esc(c.name)}.</p>`, "✓ Ja, los!");
}

function deletePlate(p) {
  const what = { waiting: "Die Namen kommen auf eine neue Platte.", error: "Die Namen kommen auf eine neue Platte.",
    printing: "⚠️ Der Druck wird gestoppt! Die Namen kommen auf eine neue Platte.",
    done: "Sie verschwindet nur aus der Liste." }[p.state];
  act(`/api/staff/plates/${p.id}/delete`, `<p class="q">🗑️ Platte ${p.id} löschen?</p><p>${what}</p>
    <p><b>Bist du sicher?</b></p>`, "🗑️ Ja, löschen", "danger-solid");
}

$("plates").addEventListener("click", (e) => {
  const el = e.target.closest("[data-start],[data-del],[data-sim],[data-show]");
  if (!el || el.disabled) return;
  const find = (id) => data.plates.find((p) => p.id === Number(id));
  if (el.dataset.start) startPlate(find(el.dataset.start));
  else if (el.dataset.del) deletePlate(find(el.dataset.del));
  else if ("sim" in el.dataset) act("/api/staff/sim/resume");
  else showPreview(Number(el.dataset.show));
});

// ---------------------------------------------------------------- pickup
function renderOrders() {
  const orders = data.orders.slice().sort((a, b) => (b.ready - a.ready) || (a.number - b.number));
  $("orders").innerHTML = orders.map((o) => {
    const due = !o.paid && o.price_cents > 0;
    const live = o.tags.filter((t) => t.status !== "cancelled");
    const tags = live.map((t) => `<span class="tag">${TAG_ICON[t.status] || ""} ${dot(color(t.text_color).hex)}
      <b>${esc(t.name)}</b>${["held", "queued"].includes(t.status)
        ? `<button class="x" data-cancel-tag="${t.id}" data-name="${esc(t.name)}" title="Stornieren">✕</button>` : ""}</span>`).join("");
    return `<div class="order${o.ready ? " ready" : ""}">
      <div class="order-main">
        <span class="onum">#${o.number}</span>
        ${o.customer ? `<span class="customer">${esc(o.customer)}</span>` : ""}
        ${o.day !== data.today ? `<span class="chip">${esc(o.day.slice(8))}.${esc(o.day.slice(5, 7))}.</span>` : ""}
        <span class="spacer"></span>
        ${due ? `<button class="money" data-paid="${o.id}" title="Schon bezahlt">💶 ${euro(o.price_cents)}</button>` : ""}
        ${o.ready ? `<button class="big primary" data-pickup="${o.id}">🎁 Abgeholt</button>` : ""}
        <button class="big icon danger" data-cancel="${o.id}" title="Stornieren">🗑️</button>
      </div>
      <div class="tags">${tags}</div>
    </div>`;
  }).join("") || `<p class="empty">Keine Bestellungen.</p>`;
}

$("orders").addEventListener("click", (e) => {
  const el = e.target.closest("button");
  if (!el) return;
  const o = data.orders.find((x) => x.id === Number(el.dataset.pickup || el.dataset.paid || el.dataset.cancel));
  const who = o ? `#${o.number}${o.customer ? " " + esc(o.customer) : ""}` : "";
  if (el.dataset.pickup) {
    const due = !o.paid && o.price_cents > 0;
    act(`/api/staff/orders/${o.id}/pickup`, due
      ? `<p class="q">💶 ${euro(o.price_cents)} bekommen?</p><p>Dann ist ${who} abgeholt.</p>`
      : `<p class="q">🎁 ${who} abgeholt?</p>`, due ? "✓ Ja, Geld da" : "✓ Ja");
  } else if (el.dataset.paid) {
    act(`/api/staff/orders/${o.id}/paid`, `<p class="q">💶 ${who} hat ${euro(o.price_cents)} schon bezahlt?</p>`);
  } else if (el.dataset.cancel) {
    act(`/api/staff/orders/${o.id}/cancel`, `<p class="q">🗑️ Bestellung ${who} stornieren?</p>
      <p>Nicht gedruckte Namen werden gelöscht.</p><p><b>Bist du sicher?</b></p>`, "🗑️ Ja, stornieren", "danger-solid");
  } else if (el.dataset.cancelTag) {
    act(`/api/staff/tags/${el.dataset.cancelTag}/cancel`, `<p class="q">✕ ${esc(el.dataset.name)} stornieren?</p>
      <p><b>Bist du sicher?</b></p>`, "✕ Ja, stornieren", "danger-solid");
  }
});

// ---------------------------------------------------------------- page
function render() {
  const [txt, cls, icon] = PRINTER[data.printer.state] || [data.printer.state, "", "❔"];
  $("printerChip").textContent = `${icon} ${txt}${data.printer.kind === "sim" ? " (Sim)" : ""}`;
  $("printerChip").className = "status " + cls;
  $("etaAll").textContent = data.eta_all_s > 0 ? `alles fertig in ca. ${mins(data.eta_all_s)}` : "";
  renderPlates(); renderOrders();
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
  catch (e) { if (e.message !== "login") { $("printerChip").textContent = "📵 Server nicht erreichbar"; $("printerChip").className = "status bad"; } }
}

$("loginBtn").onclick = login;
$("pin").addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });
if (token) { $("app").classList.remove("hidden"); refresh(); } else showLogin();
setInterval(refresh, 2000);
