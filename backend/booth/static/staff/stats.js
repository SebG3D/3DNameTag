// Staff page: day view (stats, CSV export, backup, close day). Uses api(), esc(), $, euro, dot from staff.js.
"use strict";

const colorName = (st, id) => (st.colors.find((c) => c.id === id) || { name: id }).name;
const colorHex = (st, id) => (st.colors.find((c) => c.id === id) || { hex: "#888" }).hex;
const fmtDay = (d) => `${d.slice(8)}.${d.slice(5, 7)}.`;

function counts(obj, label = (k) => k) {
  const e = Object.entries(obj).sort((a, b) => b[1] - a[1]);
  return e.length ? e.map(([k, n]) => `${label(k)} <b>${n}</b>`).join(" · ") : "–";
}

function renderStats(st) {
  const t = st.today, cp = st.close_preview;
  const lb = st.last_backup;
  const SH = typeof SHAPE !== "undefined" ? SHAPE : {};
  $("statsView").innerHTML = `
  <section class="card"><h2>Heute (${fmtDay(t.day)})</h2>
    <div class="kpis">
      <div><b>${t.orders}</b><span>Bestellungen</span></div>
      <div><b>${t.tags_printed}</b><span>gedruckt</span></div>
      <div><b>${t.tags_open}</b><span>offen</span></div>
      <div><b>${euro(t.paid_cents)}</b><span>kassiert</span></div>
    </div>
    ${t.due_cents ? `<p class="err">${euro(t.due_cents)} noch nicht bezahlt</p>` : ""}
    <p class="muted">${t.free_tags} gratis · ${t.tags_cancelled} storniert · ${t.plates_done} Platten
      (${t.print_h} h Druckzeit)${t.plates_failed ? ` · ${t.plates_failed} fehlgeschlagen/abgebrochen` : ""}</p>
    <p class="muted">Wartezeit bis gedruckt: Ø ${t.wait_avg_min} min, max. ${t.wait_max_min} min</p>
    <p>Textfarben gedruckt: ${counts(t.by_color, (k) => dot(colorHex(st, k)) + esc(colorName(st, k)))}</p>
    <p class="muted">Formen: ${counts(t.by_shape, (k) => esc(SH[k] || k))}</p>
    <p class="muted">Schriften: ${counts(t.by_font, esc)}</p>
    <div class="row">
      <a class="btnlink" href="/api/staff/export.csv?day=${t.day}&token=${encodeURIComponent(token)}">CSV heute</a>
      <a class="btnlink" href="/api/staff/export.csv?token=${encodeURIComponent(token)}">CSV alle Tage</a>
    </div>
  </section>

  ${st.days.length ? `<section class="card"><h2>Vorherige Tage</h2>
    <table class="days"><tr><th>Tag</th><th>Best.</th><th>gedruckt</th><th>kassiert</th><th></th></tr>
    ${st.days.map((d) => `<tr><td>${fmtDay(d.day)}</td><td>${d.orders}</td><td>${d.tags_printed}</td>
      <td>${euro(d.paid_cents)}</td><td><a href="/api/staff/export.csv?day=${d.day}&token=${encodeURIComponent(token)}">CSV</a></td></tr>`).join("")}
    </table></section>` : ""}

  <section class="card"><h2>Datensicherung</h2>
    <p class="muted">Automatisch jede Stunde und beim Tagesabschluss.
      ${lb ? `Letzte: ${new Date(lb.t * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })} Uhr` : "Noch keine."}</p>
    <button class="small" id="backupBtn">Jetzt sichern</button> <span id="backupMsg" class="muted"></span>
  </section>

  <section class="card" id="systemCard"><h2>Kiosk-Rechner</h2>
    <p class="muted" id="sysInfo"></p>
    <div class="row">
      <button class="small" id="syncBtn">Uhrzeit vom Handy übernehmen</button>
      <button class="small" id="rebootBtn">Neu starten</button>
      <button class="danger small" id="offBtn">Herunterfahren</button>
    </div>
  </section>

  <section class="card"><h2>Tag abschließen</h2>
    <p>Am Ende des Standtags. Danach ist die Liste leer; die Abholnummern fangen am nächsten Tag ohnehin bei 1 an.</p>
    <ul>
      <li>${cp.tags_unprinted} noch nicht gedruckte Anhänger werden storniert${cp.orders_unpaid ? ` (${cp.orders_unpaid} Bestellungen unbezahlt)` : ""}</li>
      <li>${cp.orders_waiting_pickup} fertige, nicht abgeholte Bestellungen werden geschlossen (Anhänger in die Restekiste)</li>
      <li>Druckdateien erledigter Platten werden gelöscht, eine Sicherung wird angelegt</li>
    </ul>
    ${cp.plate_active ? `<div class="lock">Erst die laufende Platte fertig drucken und abnehmen.</div>` : ""}
    <button class="danger" id="closeDayBtn" ${cp.plate_active ? "disabled" : ""}>Tag abschließen</button>
    <span id="closeMsg" class="muted"></span>
  </section>`;

  api("/api/staff/system").then((sys) => {
    const t = new Date(sys.time * 1000).toLocaleString("de-DE");
    $("sysInfo").textContent = sys.allowed ? `Uhrzeit des Kiosk-Rechners: ${t}` : "Nur auf dem Kiosk-Pi verfügbar.";
    for (const id of ["syncBtn", "rebootBtn", "offBtn"]) $(id).disabled = !sys.allowed;
  }).catch(() => {});
  $("syncBtn").onclick = async () => { await syncClock(); loadStats(); };
  const power = (action, text) => async () => {
    if (!confirm(text)) return;
    try { await api(`/api/staff/system/${action}`, { method: "POST" }); $("sysInfo").textContent = "OK – Sicherung angelegt, Rechner " + (action === "reboot" ? "startet neu" : "fährt herunter") + " …"; }
    catch (e) { alert(e.message); }
  };
  $("rebootBtn").onclick = power("reboot", "Kiosk-Rechner neu starten?");
  $("offBtn").onclick = power("poweroff", "Kiosk-Rechner herunterfahren? Danach Stecker ziehen ist sicher.");
  $("backupBtn").onclick = async () => {
    try { const r = await api("/api/staff/backup", { method: "POST" }); $("backupMsg").textContent = "gesichert ✓"; loadStats(); }
    catch (e) { $("backupMsg").textContent = e.message; }
  };
  $("closeDayBtn").onclick = async () => {
    if (!confirm(`Tag wirklich abschließen? ${cp.tags_unprinted} Anhänger werden storniert.`)) return;
    try { await api("/api/staff/close_day", { method: "POST" }); await loadStats(); $("closeMsg").textContent = "Tag abgeschlossen ✓"; }
    catch (e) { $("closeMsg").textContent = e.message; }
  };
}

async function loadStats() {
  try { renderStats(await api("/api/staff/stats")); }
  catch (e) { if (e.message !== "login") $("statsView").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
}

function showStats(on) {
  if (on) showSettings(false);
  $("statsView").classList.toggle("hidden", !on);
  $("overview").classList.toggle("hidden", on || !$("settingsView").classList.contains("hidden"));
  $("statsBtn").classList.toggle("primary", on);
  if (on) loadStats();
  window.scrollTo(0, 0);
}

$("statsBtn").onclick = () => showStats($("statsView").classList.contains("hidden"));
