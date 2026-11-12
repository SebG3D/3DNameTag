// Staff page: settings view (GET/PUT /api/staff/settings). Uses api(), esc(), $ from staff.js.
"use strict";

let S = null;            // response of GET /api/staff/settings (with .settings being edited)

const slug = (name, taken) => {
  let base = name.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 16) || "farbe";
  let id = base, n = 2;
  while (taken.has(id)) id = `${base}-${n++}`;
  return id;
};

function field(label, input, help = "") {
  return `<label class="field"><span>${label}</span>${input}${help ? `<small>${help}</small>` : ""}</label>`;
}
const num = (key, val, attrs = "") => `<input type="number" inputmode="decimal" data-k="${key}" value="${esc(val)}" ${attrs}>`;
const txt = (key, val, attrs = "") => `<input type="text" data-k="${key}" value="${esc(val ?? "")}" ${attrs}>`;

function renderSettings() {
  const d = S.settings, p = d.printer;
  const inUse = new Set(S.colors_in_use);
  const colors = d.text_colors.map((c, i) => `
    <div class="colorrow">
      <input type="color" data-color="${i}" value="${esc(c.hex.toLowerCase())}">
      <input type="text" data-cname="${i}" value="${esc(c.name)}" maxlength="20">
      ${inUse.has(c.id) ? `<span class="muted" title="offene Anhänger">in Benutzung</span>`
        : `<button class="danger small" data-delcolor="${i}">✕</button>`}
    </div>`).join("");
  const setupLocked = S.setup_locked || S.open_tags > 0 || S.plate_active;
  const setups = S.setups.map((s) => `<option value="${esc(s.name)}" ${s.name === S.current_setup ? "selected" : ""}>
      ${esc(s.name)} – Skalierung ${s.scale}, min. Text ${s.min_text_size} mm${s.default ? " (Standard)" : ""}</option>`).join("");
  const toggles = (list, disabled, key) => list.map((x) => `<label class="check">
      <input type="checkbox" data-${key}="${esc(x.id)}" ${disabled.includes(x.id) ? "" : "checked"}> ${esc(x.label)}</label>`).join("");

  $("settingsForm").innerHTML = `
  <section class="card"><h2>Stand</h2>
    ${field("Name der Veranstaltung (Startbildschirm)", txt("event_name", d.event_name, 'maxlength="60"'))}
  </section>

  <section class="card"><h2>Farben</h2>
    <div class="field"><span>Grundfarbe (eingelegtes Filament für den Anhänger)</span>
      <div class="colorrow"><input type="color" id="baseHex" value="${esc(d.base_color.hex.toLowerCase())}">
        <input type="text" id="baseName" value="${esc(d.base_color.name)}" maxlength="20"></div></div>
    <div class="field"><span>Textfarben (vorhandene Rollen, Kinder wählen daraus)</span>${colors}
      <button class="small" id="addColor">+ Farbe</button></div>
  </section>

  <section class="card"><h2>Preise &amp; Mengen</h2>
    <div class="grid2">
      ${field("Gratis-Anhänger pro Bestellung", num("pricing.free_tags", d.pricing.free_tags, 'min="0" max="10"'))}
      ${field("Preis je weiterem Anhänger (€)", `<input type="number" step="0.10" min="0" id="priceEuro" value="${(d.pricing.price_per_extra_cents / 100).toFixed(2)}">`)}
      ${field("Max. Anhänger pro Bestellung", num("max_tags_per_order", d.max_tags_per_order, 'min="1" max="20"'))}
      ${field("Warteschlangen-Limit", num("queue_limit", d.queue_limit, 'min="1" max="500"'), "offene Anhänger; danach nimmt der Kiosk keine Bestellung an")}
    </div>
  </section>

  <section class="card"><h2>Druckplatten</h2>
    <div class="grid2">
      ${field("Max. Anhänger pro Platte", num("plate.max_tags", d.plate.max_tags, 'min="1" max="40"'), "was nicht auf die Platte passt, kommt auf die nächste")}
      ${field("Startempfehlung nach (min)", num("plate.max_wait_min", d.plate.max_wait_min, 'min="0" max="240"'), "⭐ empfiehlt eine Platte, auch wenn sie nicht voll ist (gestartet wird immer von Hand)")}
      ${field("Wechselzeit Betreuer (min)", num("plate.change_min", d.plate.change_min, 'min="0" max="60" step="0.5"'), "Platte leeren + Filament, für die Zeitschätzung")}
      ${field("Vorbereitung Drucker (min)", num("plate.prep_min", d.plate.prep_min, 'min="0" max="30" step="0.5"'), "Aufheizen + Vermessen + Ende je Platte, für die Zeitschätzung")}
    </div>
  </section>

  <section class="card"><h2>Kiosk</h2>
    <div class="grid2">
      <div class="field"><span>Schriften</span>${toggles(S.fonts, d.disabled_fonts, "font")}</div>
      <div class="field"><span>Formen</span>${toggles(S.shapes, d.disabled_shapes, "shape")}</div>
    </div>
    <div class="grid2">
      ${field("Inaktivität bis „Bist du noch da?“ (s)", num("kiosk.idle_s", d.kiosk.idle_s, 'min="20" max="600"'))}
      <label class="check" style="margin-top:28px"><input type="checkbox" id="sound" ${d.kiosk.sound ? "checked" : ""}> Tastenklick-Ton</label>
    </div>
    <p class="muted">Der Kiosk übernimmt Änderungen, sobald er wieder auf dem Startbildschirm ist.</p>
  </section>

  <section class="card"><h2>Drucker</h2>
    ${S.plate_active ? `<div class="lock">Während eine Platte läuft, kann der Drucker nicht geändert werden.</div>` : ""}
    ${field("Typ", `<select data-k="printer.type" id="ptype" ${S.plate_active ? "disabled" : ""}>
        <option value="sim" ${p.type === "sim" ? "selected" : ""}>Simulator (ohne Drucker)</option>
        <option value="prusalink" ${p.type === "prusalink" ? "selected" : ""}>Prusa Core One (PrusaLink)</option></select>`)}
    <div id="plFields" class="${p.type === "prusalink" ? "" : "hidden"}">
      <div class="grid2">
        ${field("Host / IP", txt("printer.host", p.host, 'placeholder="192.168.10.2"'))}
        ${field("Benutzer", txt("printer.user", p.user), "Drucker: Einstellungen › Netzwerk › PrusaLink")}
        ${field("Passwort", `<input type="password" data-k="printer.password" autocomplete="off" placeholder="${p.has_password ? "gespeichert – leer lassen" : "aus dem Drucker-Menü"}">`)}
        ${field("API-Key (nur ältere Firmware)", `<input type="password" data-k="printer.api_key" autocomplete="off" placeholder="${p.has_api_key ? "gespeichert – leer lassen" : "leer lassen"}">`, "wenn gesetzt, wird er statt Passwort benutzt")}
      </div>
    </div>
    <div id="simFields" class="${p.type === "sim" ? "" : "hidden"}">
      ${field("Sim-Geschwindigkeit (x Echtzeit)", num("printer.sim_speed", p.sim_speed ?? 60, 'min="1" max="1000"'))}
    </div>
    <p class="muted">Die Platten werden auf den USB-Stick im Drucker geladen – Stick muss stecken.</p>
    <div class="row"><button class="small" id="testPrinter">Verbindung testen</button><span id="testMsg" class="muted"></span></div>
  </section>

  <section class="card"><h2>Druck-Setup (Düse)</h2>
    ${setupLocked ? `<div class="lock">${S.setup_locked ? "Per --setup beim Start festgelegt." :
      "Nur änderbar, wenn keine Anhänger offen sind und keine Platte läuft."}</div>` : ""}
    ${field("Setup aus config/print.json", `<select id="setup" ${setupLocked ? "disabled" : ""}>${setups}</select>`,
      "Bestimmt Größe und Mindest-Textgröße. Passend zur eingebauten Düse wählen.")}
  </section>

  <section class="card"><h2>Betreuer-PIN</h2>
    ${S.pin_from_env ? `<div class="lock">PIN kommt aus der Umgebungsvariable BOOTH_PIN.</div>` :
      field("Neue PIN (leer = unverändert)", `<input type="password" inputmode="numeric" id="newPin" autocomplete="new-password" maxlength="8" placeholder="4–8 Ziffern">`)}
  </section>`;

  $("ptype").onchange = (e) => {
    $("plFields").classList.toggle("hidden", e.target.value !== "prusalink");
    $("simFields").classList.toggle("hidden", e.target.value !== "sim");
  };
  $("addColor").onclick = () => { collect(); const taken = new Set(S.settings.text_colors.map((c) => c.id));
    S.settings.text_colors.push({ id: slug("neu", taken), name: "", hex: "#888888", _new: true }); renderSettings(); };
  document.querySelectorAll("[data-delcolor]").forEach((b) => b.onclick = () => {
    collect(); S.settings.text_colors.splice(+b.dataset.delcolor, 1); renderSettings(); });
  $("testPrinter").onclick = testPrinter;
}

function setPath(obj, path, v) {
  const ks = path.split(".");
  let o = obj;
  for (const k of ks.slice(0, -1)) o = o[k] ??= {};
  o[ks.at(-1)] = v;
}

// form -> S.settings (numbers as numbers; empty secret fields = unchanged)
function collect() {
  const d = S.settings;
  document.querySelectorAll("#settingsForm [data-k]").forEach((el) => {
    let v = el.value;
    if (el.type === "number") v = v === "" ? NaN : Number(v);
    setPath(d, el.dataset.k, v);
  });
  d.base_color = { name: $("baseName").value.trim(), hex: $("baseHex").value };
  const taken = new Set();
  d.text_colors = d.text_colors.map((c, i) => {
    const name = document.querySelector(`[data-cname="${i}"]`).value.trim();
    const hex = document.querySelector(`[data-color="${i}"]`).value;
    const id = c._new ? slug(name || "farbe", new Set([...taken, ...d.text_colors.filter((x) => !x._new).map((x) => x.id)])) : c.id;
    taken.add(id);
    return c._new ? { id, name, hex, _new: true } : { id, name, hex };
  });
  d.pricing.price_per_extra_cents = Math.round(Number($("priceEuro").value) * 100);
  d.disabled_fonts = [...document.querySelectorAll("[data-font]")].filter((x) => !x.checked).map((x) => x.dataset.font);
  d.disabled_shapes = [...document.querySelectorAll("[data-shape]")].filter((x) => !x.checked).map((x) => x.dataset.shape);
  d.kiosk.sound = $("sound").checked;
  const def = S.setups.find((s) => s.default);
  d.print_setup = $("setup").value === def?.name ? null : $("setup").value;
  if ($("newPin")) d.staff_pin = $("newPin").value.trim();
  return d;
}

function payload() {
  const d = structuredClone(collect());
  d.text_colors = d.text_colors.map(({ _new, ...c }) => c);
  return d;
}

async function loadSettings() {
  $("settingsMsg").textContent = "";
  S = await api("/api/staff/settings");
  renderSettings();
}

async function saveSettings() {
  const msg = $("settingsMsg");
  msg.className = "muted"; msg.textContent = "Speichere …";
  try {
    S = await api("/api/staff/settings", { method: "PUT", body: JSON.stringify(payload()) });
    renderSettings();
    msg.className = "chip ok"; msg.textContent = "Gespeichert ✓";
  } catch (e) {
    if (e.message === "login") return;
    msg.className = "err"; msg.textContent = e.message;
  }
}

async function testPrinter() {
  $("testMsg").textContent = "teste …";
  try {
    const r = await api("/api/staff/printer/test", { method: "POST", body: JSON.stringify(payload().printer) });
    const [t] = PRINTER[r.state] || [r.state];
    $("testMsg").innerHTML = (r.state === "offline" ? `<span class="err">nicht erreichbar</span> ` : `<b>${esc(t)}</b> `) + esc(r.message || "");
  } catch (e) { $("testMsg").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
}

function showSettings(on) {
  if (on) showStats(false);
  $("settingsView").classList.toggle("hidden", !on);
  $("overview").classList.toggle("hidden", on);
  $("settingsBtn").classList.toggle("primary", on);
  if (on) loadSettings().catch((e) => { if (e.message !== "login") $("settingsMsg").textContent = e.message; });
  window.scrollTo(0, 0);
}

$("settingsBtn").onclick = () => showSettings($("settingsView").classList.contains("hidden"));
$("settingsCancel").onclick = () => showSettings(false);
$("settingsSave").onclick = saveSettings;
