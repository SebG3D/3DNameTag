// On-screen keyboard for the staff page on a touch screen without a keyboard
// (second booth screen). Only active when the page was opened with ?osk=1
// (kiosk.sh staff, or the 5-tap link on the customer kiosk); phones keep their own.
// Works on every text/password/number/time input that appears later too (focusin).
"use strict";

(() => {
  const params = new URLSearchParams(location.search);
  try {
    if (params.has("osk")) sessionStorage.setItem("osk", params.get("osk") === "0" ? "0" : "1");
    if (sessionStorage.getItem("osk") !== "1") return;
  } catch { if (!params.has("osk") || params.get("osk") === "0") return; }

  const TEXT_TYPES = new Set(["text", "password", "search", "email", "url", "tel", ""]);
  const LAYOUTS = {
    abc: [
      ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "ß"],
      ["q", "w", "e", "r", "t", "z", "u", "i", "o", "p", "ü"],
      ["a", "s", "d", "f", "g", "h", "j", "k", "l", "ö", "ä"],
      ["⇧", "y", "x", "c", "v", "b", "n", "m", ",", ".", "-", "⌫"],
      ["#+=", "😀", "←", " ", "→", "✓"],
    ],
    sym: [
      ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
      ["!", "?", "\"", "'", "§", "$", "€", "%", "&", "/"],
      ["(", ")", "=", "+", "*", "#", "@", ":", ";", "_"],
      ["<", ">", "[", "]", "{", "}", "|", "\\", "~", "^", "⌫"],
      ["abc", "😀", "←", " ", "→", "✓"],
    ],
    emoji: [
      ["🍪", "🎄", "⭐", "❄️", "⛄", "🎅", "🦌", "🔔", "🎁", "🕯️"],
      ["🐉", "🐍", "🦄", "🐱", "🐶", "🦊", "🐻", "🐰", "🦖", "🐢"],
      ["⚡", "🔥", "💖", "🌈", "🌟", "🍀", "⚽", "🚀", "🛍️", "🧸"],
      ["😊", "😎", "🤩", "👍", "🎉", "🏆", "🎨", "🖨️", "🧾", "⌫"],
      ["abc", "#+=", "←", " ", "→", "✓"],
    ],
    num: [["7", "8", "9"], ["4", "5", "6"], ["1", "2", "3"], [".", "0", "⌫"], ["✓"]],
    time: [["7", "8", "9"], ["4", "5", "6"], ["1", "2", "3"], ["C", "0", "⌫"], ["✓"]],
  };
  const LABELS = { "⇧": "⇧", " ": "Leertaste", "✓": "✓ Fertig", "⌫": "⌫", "#+=": "#+=", "abc": "abc" };

  const graphemes = new Intl.Segmenter("de", { granularity: "grapheme" });
  let el = null, layout = "abc", shift = false, buf = "", repeat = null;

  const kb = document.createElement("div");
  kb.id = "osk";
  kb.className = "hidden";
  kb.innerHTML = `<div class="osk-top"><span class="osk-label"></span><span class="osk-value"></span></div><div class="osk-keys"></div>`;
  document.body.appendChild(kb);
  const keysEl = kb.querySelector(".osk-keys");

  const mode = (input) => input.type === "number" ? "num" : input.type === "time" ? "time" : "text";

  function wanted(t) {
    if (!(t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement)) return false;
    if (t.readOnly || t.disabled || t.dataset.noOsk !== undefined) return false;
    return t instanceof HTMLTextAreaElement || TEXT_TYPES.has(t.type) || t.type === "number" || t.type === "time";
  }

  function render() {
    const m = mode(el);
    const rows = LAYOUTS[m === "text" ? layout : m];
    kb.classList.toggle("osk-narrow", m !== "text");
    keysEl.innerHTML = rows.map((row) => `<div class="osk-row">${row.map((k) => {
      const shown = m === "text" && layout === "abc" && shift && k.length === 1 ? k.toUpperCase() : k;
      const cls = k === " " ? "space" : k === "✓" ? "done" : k === "⇧" ? (shift ? "mod on" : "mod")
        : ["⌫", "#+=", "abc", "😀", "←", "→", "C"].includes(k) ? "mod" : "";
      return `<button type="button" class="${cls}" data-key="${esc(k)}">${esc(LABELS[k] ?? shown)}</button>`;
    }).join("")}</div>`).join("");
    preview();
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function timeText() {
    const d = buf.padEnd(4, "_");
    return `${d.slice(0, 2)}:${d.slice(2)}`;
  }

  function preview() {
    const lab = el.closest("label")?.querySelector("span")?.textContent || el.placeholder || "";
    kb.querySelector(".osk-label").textContent = lab;
    const m = mode(el);
    const v = m === "num" ? buf : m === "time" ? timeText() : el.value;
    kb.querySelector(".osk-value").textContent = el.type === "password" ? "•".repeat(v.length) : v;
  }

  function fire(type) { el.dispatchEvent(new Event(type, { bubbles: true })); }

  function insert(t) {
    const v = el.value;
    let s = el.selectionStart ?? v.length, e = el.selectionEnd ?? s;
    const nv = v.slice(0, s) + t + v.slice(e);
    if (el.maxLength > 0 && nv.length > el.maxLength) return;
    el.value = nv;
    el.setSelectionRange(s + t.length, s + t.length);
    fire("input");
  }

  function backspace() {
    const v = el.value;
    let s = el.selectionStart ?? v.length, e = el.selectionEnd ?? s;
    if (s === e) {
      if (s === 0) return;
      // one whole character: an emoji like ❄️ is several code units
      const parts = [...graphemes.segment(v.slice(0, s))];
      s -= parts[parts.length - 1].segment.length;
    }
    el.value = v.slice(0, s) + v.slice(e);
    el.setSelectionRange(s, s);
    fire("input");
  }

  function setBufValue() {
    const m = mode(el);
    if (m === "num") el.value = buf;          // "2." is invalid for type=number: shows empty until the next digit
    else if (m === "time") {
      if (!buf) el.value = "";
      else if (buf.length === 4) {
        const h = +buf.slice(0, 2), mi = +buf.slice(2);
        if (h < 24 && mi < 60) el.value = `${buf.slice(0, 2)}:${buf.slice(2)}`;
      }
    }
    fire("input");
  }

  function press(k) {
    if (!el) return;
    const m = mode(el);
    if (k === "✓") { done(); return; }
    if (m !== "text") {
      if (k === "⌫") buf = buf.slice(0, -1);
      else if (k === "C") buf = "";
      else if (m === "num") {
        if (k === "." && buf.includes(".")) return;
        buf += k;
      } else if (buf.length < 4) buf += k;
      setBufValue(); preview(); return;
    }
    if (k === "⇧") { shift = !shift; render(); return; }
    if (k === "#+=") { layout = "sym"; render(); return; }
    if (k === "abc") { layout = "abc"; render(); return; }
    if (k === "😀") { layout = "emoji"; render(); return; }
    if (k === "⌫") backspace();
    else if (k === "←" || k === "→") {
      const p = Math.max(0, Math.min(el.value.length, (el.selectionStart ?? 0) + (k === "←" ? -1 : 1)));
      el.setSelectionRange(p, p);
    } else {
      insert(layout === "abc" && shift ? k.toUpperCase() : k);
      if (shift) { shift = false; render(); return; }
    }
    preview();
  }

  function show(t) {
    if (el && el !== t) el.dispatchEvent(new Event("change", { bubbles: true }));
    el = t;
    layout = "abc";
    const m = mode(el);
    buf = m === "time" ? el.value.replace(":", "").slice(0, 4) : m === "num" ? el.value : "";
    shift = m === "text" && el.value === "" && el.type !== "password";   // names start with a capital
    render();
    kb.classList.remove("hidden");
    document.body.classList.add("osk-open");
    document.documentElement.style.setProperty("--osk-h", kb.offsetHeight + "px");
    // centre the field in the space above the keyboard
    setTimeout(() => {
      if (!el) return;
      const r = el.getBoundingClientRect(), free = innerHeight - kb.offsetHeight;
      if (r.top < 0 || r.bottom > free) window.scrollBy({ top: r.top + r.height / 2 - free / 2, behavior: "smooth" });
    }, 50);
  }

  function hide() {
    kb.classList.add("hidden");
    document.body.classList.remove("osk-open");
    el = null;
  }

  function done() {
    const t = el;
    hide();
    if (t) { t.dispatchEvent(new Event("change", { bubbles: true })); t.blur(); }
  }

  document.addEventListener("focusin", (e) => { if (wanted(e.target)) show(e.target); else if (el) hide(); });
  document.addEventListener("focusout", () => {
    // tapping a key keeps the focus (pointerdown below); anything else that blurs closes it
    setTimeout(() => { if (el && document.activeElement !== el) done(); }, 0);
  });

  function stopRepeat() { clearTimeout(repeat); clearInterval(repeat); repeat = null; }
  kb.addEventListener("pointerdown", (e) => {
    e.preventDefault();                       // keep the focus in the input
    const b = e.target.closest("button");
    if (!b) return;
    const k = b.dataset.key;
    b.classList.add("down");
    press(k);
    if (k === "⌫" || k === "←" || k === "→") {
      stopRepeat();
      repeat = setTimeout(() => { repeat = setInterval(() => press(k), 70); }, 450);
    }
  });
  const up = () => { stopRepeat(); kb.querySelectorAll(".down").forEach((b) => b.classList.remove("down")); };
  kb.addEventListener("pointerup", up);
  kb.addEventListener("pointercancel", up);
  kb.addEventListener("pointerleave", up);
  kb.addEventListener("mousedown", (e) => e.preventDefault());
  kb.addEventListener("contextmenu", (e) => e.preventDefault());
})();
