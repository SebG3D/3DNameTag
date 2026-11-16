// Staff page: Kasse (till). Other items we sell at the booth (prices from settings,
// price 0 = asked here) plus maybe one tag order; sum, money given, change.
// Uses $, api, ask, tell, esc, euro, data, refresh, showTab, tabEnter from staff.js.
"use strict";

// cart lives only here: survives tab switches, cleared after a checkout
const cart = { order: null, lines: [], given: null };   // lines: {id, name, emoji, price_cents, qty}

const cartOrder = () => (cart.order == null ? null : data.orders.find((o) => o.id === cart.order) || null);
const orderDue = (o) => (o && !o.paid ? o.price_cents : 0);
const cartTotal = () => orderDue(cartOrder()) + cart.lines.reduce((s, l) => s + l.price_cents * l.qty, 0);
const orderLabel = (o) => `#${o.number}${o.customer ? " " + esc(o.customer) : ""}`;

// from the 🖨️ tab: this customer's tags go into the basket; paying happens only here.
// Tapping it again (already in the basket) takes it out.
async function kasseAdd(o) {
  if (!o) return;
  if (cart.order === o.id) cart.order = null;
  else {
    const old = cartOrder();
    if (old && !(await ask(`<p class="q">🧾 Im Korb ist schon ${orderLabel(old)}.</p>
      <p>Stattdessen ${orderLabel(o)} in den Korb?</p>`, "✓ Ja, tauschen"))) return;
    cart.order = o.id;
  }
  cart.given = null;
  renderKasse(); renderOrders();
}

// count on the 🧾 tab button, so the basket is seen from the other tabs
function renderCartBadge() {
  const n = (cartOrder() ? 1 : 0) + cart.lines.reduce((s, l) => s + l.qty, 0);
  $("cartBadge").textContent = n;
  $("cartBadge").classList.toggle("hidden", !n);
}

function addItem(it, price) {
  sfx.play(it.sound || "bells");
  const p = price ?? it.price_cents;
  const same = cart.lines.find((l) => l.id === it.id && l.price_cents === p);
  if (same) same.qty = Math.min(99, same.qty + 1);
  else cart.lines.push({ id: it.id, name: it.name, emoji: it.emoji, price_cents: p, qty: 1 });
  cart.given = null;
  renderKasse();
}

// ---------------------------------------------------------------- keypad (cents: 2 5 0 -> 2,50 €)
let keypadDone = null, keypadCents = 0;
function keypad(title) {
  keypadCents = 0;
  $("keypadTitle").innerHTML = title;
  $("keypadValue").textContent = euro(0);
  $("keypad").classList.remove("hidden");
  return new Promise((resolve) => { keypadDone = resolve; });
}
$("keypad").addEventListener("click", (e) => {
  const k = e.target.closest("[data-key]")?.dataset.key;
  if (!k) return;
  if (k === "ok" || k === "no") {
    $("keypad").classList.add("hidden");
    keypadDone?.(k === "ok" && keypadCents > 0 ? keypadCents : null);
    keypadDone = null;
    return;
  }
  if (k === "back") keypadCents = Math.floor(keypadCents / 10);
  else if (keypadCents < 1000000) keypadCents = keypadCents * (k === "00" ? 100 : 10) + (k === "00" ? 0 : Number(k));
  $("keypadValue").textContent = euro(keypadCents);
});

// ---------------------------------------------------------------- render
function renderKasse() {
  if (!data) return;
  let o = cartOrder();
  if (cart.order != null && (!o || o.paid)) cart.order = null;   // picked up / cancelled / paid meanwhile
  o = cartOrder();
  renderCartBadge();
  if (tab !== "kasse") return;
  $("shopItems").innerHTML = (data.shop_items || []).map((it) =>
    `<button class="big shop" data-item="${esc(it.id)}"><span class="semoji">${esc(it.emoji || "🛍️")}</span>
      <span class="sname">${esc(it.name)}</span>
      <span class="sprice">${it.price_cents ? euro(it.price_cents) : "Preis?"}</span></button>`).join("") ||
    `<p class="empty">Keine Artikel – in ⚙️ Einstellungen anlegen.</p>`;

  const total = cartTotal();
  const orderRow = o
    ? `<div class="rline order-line"><span>🏷️ ${orderLabel(o)} · ${o.tags.filter((t) => t.status !== "cancelled").length} Anhänger</span>
        <span class="spacer"></span><b>${o.paid ? `<span class="muted">bezahlt</span>` : euro(o.price_cents)}</b>
        <button class="icon danger" data-unorder title="Bestellung weg">✕</button></div>`
    : `<button class="big full" data-pick-order>🏷️ Bestellung dazu …</button>`;
  const lines = cart.lines.map((l, i) => `<div class="rline">
      <span>${esc(l.emoji || "🛍️")} ${esc(l.name)}</span><span class="muted">${euro(l.price_cents)}</span>
      <span class="spacer"></span>
      <button class="icon" data-minus="${i}">−</button><b class="qty">${l.qty}</b><button class="icon" data-plus="${i}">+</button>
      <b class="ltotal">${euro(l.price_cents * l.qty)}</b></div>`).join("");
  const given = cart.given;
  let change = "";
  if (given != null) {
    change = given >= total
      ? `<div class="change ok">Rückgeld <b>${euro(given - total)}</b></div>`
      : `<div class="change bad">Fehlt noch <b>${euro(total - given)}</b></div>`;
  }
  const canPay = (o || cart.lines.length) && (total === 0 || (given != null && given >= total));
  $("receipt").innerHTML = `
    ${orderRow}
    <div class="rlines">${lines || `<p class="muted">Tippe links auf einen Artikel.</p>`}</div>
    <div class="sum"><span>Summe</span><b>${euro(total)}</b></div>
    <div class="given">
      <span>Gegeben${given != null ? `: <b>${euro(given)}</b>` : ""}</span>
      <div class="row">
        <button class="big" data-given="${total}">Passend</button>
        ${[500, 1000, 2000, 5000].map((c) => `<button class="big" data-given="${c}">${c / 100} €</button>`).join("")}
        <button class="big" data-given-key>⌨️</button>
      </div>
    </div>
    ${change}
    <div class="dialog-buttons">
      <button class="big danger" data-clear>🗑️ Leeren</button>
      <button class="big primary" data-pay ${canPay ? "" : "disabled"}>✓ Bezahlt</button>
    </div>`;
}

// ---------------------------------------------------------------- actions
$("shopItems").addEventListener("click", async (e) => {
  const id = e.target.closest("[data-item]")?.dataset.item;
  const it = id && data.shop_items.find((x) => x.id === id);
  if (!it) return;
  if (it.price_cents) return addItem(it);
  const p = await keypad(`${esc(it.emoji || "🛍️")} ${esc(it.name)} – wie teuer?`);
  if (p) addItem(it, p);
});

function pickOrder() {
  const list = data.orders.slice().sort((a, b) => (b.ready - a.ready) || (a.number - b.number));
  $("modalText").innerHTML = `<p class="q">🏷️ Welche Bestellung?</p><div class="stack pick">${list.map((o) =>
    `<button class="big" data-pick="${o.id}">${o.ready ? "✅" : "⏳"} ${orderLabel(o)}
      <span class="muted">${o.paid || !o.price_cents ? "bezahlt" : euro(o.price_cents)}</span></button>`).join("") ||
    `<p class="muted">Keine offenen Bestellungen.</p>`}</div>`;
  $("modalYes").classList.add("hidden");
  $("modalNo").textContent = "✕ Abbrechen";
  $("modal").classList.remove("hidden");
}
$("modalText").addEventListener("click", (e) => {
  const id = e.target.closest("[data-pick]")?.dataset.pick;
  if (!id) return;
  closeModal(false);
  cart.order = Number(id); cart.given = null;
  renderKasse();
});

async function pay() {
  const o = cartOrder(), total = cartTotal();
  const given = total === 0 ? 0 : cart.given;
  const back = given - total;
  const q = total === 0 ? `🎁 Kostenlos – fertig?`
    : back > 0 ? `💶 ${euro(given)} bekommen?` : `💶 ${euro(total)} passend bekommen?`;
  if (!(await ask(`<p class="q">${q}</p>
    ${back > 0 ? `<p>Preis ${euro(total)} → danach <b>${euro(back)}</b> Rückgeld geben.</p>` : ""}${o ? `<p>Bestellung ${orderLabel(o)} ist dann bezahlt.</p>` : ""}`,
    total === 0 ? "✓ Ja, fertig" : "✓ Ja, Geld da"))) return;
  try {
    const r = await api("/api/staff/sales", { method: "POST", body: JSON.stringify({
      order_id: o ? o.id : null, given_cents: given,
      items: cart.lines.map((l) => ({ id: l.id, qty: l.qty, price_cents: l.price_cents })) }) });
    sfx.sale(!!o, total, cart.lines.reduce((s, l) => s + l.qty, 0) + (o ? o.tags.length : 0));
    cart.order = null; cart.lines = []; cart.given = null;
    tell(`<p class="q">✓ Bezahlt</p>${r.change_cents > 0 ? `<p class="bigmoney">Rückgeld ${euro(r.change_cents)}</p>` : ""}
      ${o ? (r.picked_up ? `<p>🎁 Anhänger ${orderLabel(o)} mitgeben!</p>`
        : `<p>⏳ Anhänger ${orderLabel(o)} sind noch nicht fertig – später abholen.</p>`) : ""}`);
    await refresh();
  } catch (e) { if (e.message !== "login") tell(`<p class="q">❌ Geht nicht</p><p>${esc(e.message)}</p>`); }
}

$("receipt").addEventListener("click", async (e) => {
  const el = e.target.closest("button");
  if (!el || el.disabled) return;
  const d = el.dataset;
  if ("unorder" in d) { cart.order = null; cart.given = null; }
  else if ("pickOrder" in d) return pickOrder();
  else if (d.minus) {
    const l = cart.lines[+d.minus];
    if (--l.qty <= 0) cart.lines.splice(+d.minus, 1);
    cart.given = null;
  } else if (d.plus) { cart.lines[+d.plus].qty = Math.min(99, cart.lines[+d.plus].qty + 1); cart.given = null; }
  else if (d.given) cart.given = Number(d.given);
  else if ("givenKey" in d) { const g = await keypad("💶 Wie viel Geld bekommen?"); if (g != null) cart.given = g; }
  else if ("clear" in d) {
    if ((cart.lines.length || cart.order != null) && !(await ask(`<p class="q">🗑️ Kasse leeren?</p>`, "🗑️ Ja, leeren", "danger-solid"))) return;
    cart.order = null; cart.lines = []; cart.given = null;
  } else if ("pay" in d) return pay();
  renderKasse();
});

tabEnter.kasse = renderKasse;
