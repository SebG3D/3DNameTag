// Ordering controls: stop/start ordering on the kiosk (with a message), closing
// time (kiosk stops taking orders that would not be ready by then), show the
// wait time on the kiosk, and reset the kiosk to its start screen.
"use strict";

function renderOrderChip() {
  const o = data.ordering, el = $("orderBtn");
  if (o.open) {
    el.textContent = `🟢 Bestellen an${o.show_wait ? ` · ⏱️ ${o.wait_min} min` : ""}`;
    el.className = "ordering ok";
  } else {
    el.textContent = o.reason === "closing" ? "🌙 Annahmeschluss" : "🔴 Bestellen aus";
    el.className = "ordering bad";
  }
  if (!$("orderPanel").classList.contains("hidden")) renderOrderStatus();
}

// the live part of the panel (refreshed every 2 s without touching the inputs)
function renderOrderStatus() {
  const o = data.ordering;
  let line;
  if (o.open) line = `<div class="banner ok">🟢 Kinder können bestellen</div>`;
  else if (o.reason === "closing") line = `<div class="banner bad">🌙 Annahmeschluss – neue Anhänger wären nicht
    bis ${esc(o.close_at)} fertig</div>`;
  else line = `<div class="banner bad">🔴 Bestellen ist aus</div><p>Kiosk zeigt: <i>„${esc(o.message)}“</i></p>`;
  const close = o.close_at
    ? `<p>Letzte Bestellung ca. <b>${esc(o.last_order)}</b> · Wartezeit jetzt ca. ${o.wait_min} min</p>`
    : `<p class="muted">Wartezeit jetzt ca. ${o.wait_min} min</p>`;
  $("orderLive").innerHTML = line + close;
}

function renderOrderPanel() {
  const o = data.ordering;
  const presets = Object.entries(data.closed_messages).map(([id, text]) =>
    `<button class="big danger stopmsg" data-stop="${esc(id)}">⏸ ${esc(text)}</button>`).join("");
  $("orderPanelBody").innerHTML = `
    <p class="q">🛒 Bestellen am Kiosk</p>
    <div id="orderLive"></div>
    ${o.manual_open ? `
      <h3>⏸ Bestellen stoppen – was soll der Kiosk sagen?</h3>
      <div class="stack">${presets}</div>
      <div class="row"><input id="ownMsg" maxlength="120" placeholder="Eigener Text …">
        <button class="big danger" data-stop-own>⏸ Stoppen</button></div>`
    : `<button class="big primary full" data-reopen>▶ Bestellen wieder an</button>`}
    <h3>🌙 Annahmeschluss (Markt schließt um)</h3>
    <div class="row"><input id="closeAt" type="time" value="${esc(o.close_at || "")}">
      <button class="big" data-close-save>✓ Setzen</button>
      ${o.close_at ? `<button class="big" data-close-off>✕ Aus</button>` : ""}</div>
    <p class="muted">Der Kiosk nimmt nur Bestellungen an, die bis dahin fertig gedruckt sind.</p>
    <h3>Kiosk</h3>
    <div class="row">
      <button class="big" data-wait>⏱️ Wartezeit zeigen: ${o.show_wait ? "<b>an</b>" : "<b>aus</b>"}</button>
      <button class="big warn" data-reset>🔄 Kiosk zurücksetzen</button>
    </div>
    <div class="dialog-buttons"><button class="big" data-panel-close>Schließen</button></div>`;
  renderOrderStatus();
}

async function setOrdering(body) {
  try {
    data.ordering = await api("/api/staff/ordering", { method: "PUT", body: JSON.stringify(body) });
    renderOrderPanel(); renderOrderChip();
  } catch (e) { if (e.message !== "login") tell(`<p class="q">❌ Geht nicht</p><p>${esc(e.message)}</p>`); }
}

$("orderBtn").onclick = () => { renderOrderPanel(); $("orderPanel").classList.remove("hidden"); };

$("orderPanel").addEventListener("click", async (e) => {
  if (e.target === $("orderPanel")) return $("orderPanel").classList.add("hidden");
  const el = e.target.closest("button");
  if (!el) return;
  const d = el.dataset;
  if ("panelClose" in d) $("orderPanel").classList.add("hidden");
  else if (d.stop) setOrdering({ open: false, message: d.stop });
  else if ("stopOwn" in d) {
    const msg = $("ownMsg").value.trim();
    if (!msg) return $("ownMsg").focus();
    setOrdering({ open: false, message: msg });
  } else if ("reopen" in d) setOrdering({ open: true });
  else if ("closeSave" in d) { if ($("closeAt").value) setOrdering({ close_at: $("closeAt").value }); }
  else if ("closeOff" in d) setOrdering({ close_at: null });
  else if ("wait" in d) setOrdering({ show_wait: !data.ordering.show_wait });
  else if ("reset" in d) {
    if (!(await ask(`<p class="q">🔄 Kiosk zurücksetzen?</p><p>Eine angefangene Bestellung wird verworfen,
      der Kiosk zeigt wieder den Startbildschirm.</p>`, "🔄 Ja, zurücksetzen", "warn"))) return;
    act("/api/staff/kiosk/reset");
  }
});
