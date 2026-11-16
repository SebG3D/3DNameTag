// Staff page sounds, all synthesized with WebAudio (no files): each Kasse item has
// its own sound (played when tapped), ka-ching on payment, fanfare for big baskets, printer alerts.
// Off when the settings say staff.sound = false or this device is muted (🔊 button).
"use strict";

const sfx = (() => {
  let ctx = null, out = null, noiseBuf = null;
  let enabled = true;
  let muted = false;
  try { muted = localStorage.getItem("staffMute") === "1"; } catch { /* private window */ }

  function audio() {
    if (!ctx) {
      ctx = new AudioContext();
      // The display speaker is powered over USB: bass and long loud sounds draw so much
      // current that the screen dropped out (roar at full volume). So: no deep bass,
      // a limiter that keeps peaks down, moderate level.
      const hp = ctx.createBiquadFilter();
      hp.type = "highpass"; hp.frequency.value = 220; hp.Q.value = 0.7;
      const comp = ctx.createDynamicsCompressor();
      comp.threshold.value = -18; comp.ratio.value = 8; comp.knee.value = 6;
      out = ctx.createGain();
      out.gain.value = 0.5;
      out.connect(hp).connect(comp).connect(ctx.destination);
      noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
      const d = noiseBuf.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    }
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  }

  // one oscillator note: freq (or [from, to] glide), start t, length, volume
  function tone(t, freq, dur, { type = "sine", vol = 0.3, attack = 0.005, to = null, dest = out } = {}) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    if (to) o.frequency.exponentialRampToValueAtTime(to, t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(vol, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(dest);
    o.start(t); o.stop(t + dur + 0.02);
    return o;
  }

  // filtered noise burst
  function noise(t, dur, { type = "bandpass", freq = 2000, q = 1, vol = 0.3, attack = 0.003, to = null } = {}) {
    const s = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    s.buffer = noiseBuf;
    s.loop = true;
    f.type = type; f.frequency.setValueAtTime(freq, t); f.Q.value = q;
    if (to) f.frequency.exponentialRampToValueAtTime(to, t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(vol, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    s.connect(f).connect(g).connect(out);
    s.start(t, Math.random()); s.stop(t + dur + 0.02);
  }

  // bell = a few inharmonic partials with a long tail
  function bell(t, f, dur = 1.0, vol = 0.25) {
    [[1, 1], [2.76, 0.4], [5.4, 0.2], [8.9, 0.08]].forEach(([m, v]) =>
      tone(t, f * m, dur / Math.sqrt(m), { vol: vol * v, attack: 0.002 }));
  }

  // each returns its length in seconds, so a sale can play them one after another
  const SOUNDS = {
    bells(t) {                                          // sleigh bells + a bell
      for (let i = 0; i < 8; i++) noise(t + i * 0.09 + Math.random() * 0.02, 0.09, { type: "highpass", freq: 7000, vol: 0.22 });
      bell(t, 1319, 0.9, 0.2); bell(t + 0.18, 1568, 0.9, 0.2);
      return 0.9;
    },
    crunch(t) {                                         // biting a cookie
      for (let i = 0; i < 6; i++) {
        const at = t + i * 0.07 + Math.random() * 0.03;
        noise(at, 0.05 + Math.random() * 0.04, { freq: 1200 + Math.random() * 2500, q: 0.8, vol: 0.5 });
      }
      return 0.55;
    },
    zap(t) {                                            // electric zap, twice
      for (const at of [t, t + 0.22]) {
        tone(at, 2400, 0.2, { type: "sawtooth", to: 150, vol: 0.18 });
        tone(at, 1800, 0.2, { type: "square", to: 90, vol: 0.08 });
        noise(at, 0.12, { type: "highpass", freq: 3000, vol: 0.12 });
      }
      return 0.5;
    },
    roar(t) {                                           // short growl; mid-range, no deep bass (power!)
      const f = ctx.createBiquadFilter(), g = ctx.createGain();
      f.type = "lowpass"; f.Q.value = 5;
      f.frequency.setValueAtTime(500, t); f.frequency.linearRampToValueAtTime(1400, t + 0.25);
      f.frequency.exponentialRampToValueAtTime(400, t + 0.7);
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.3, t + 0.12);
      g.gain.setValueAtTime(0.3, t + 0.35); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.75);
      f.connect(g).connect(out);
      for (const [fr, type] of [[165, "sawtooth"], [174, "sawtooth"], [247, "square"]]) {
        const o = ctx.createOscillator(), lfo = ctx.createOscillator(), lg = ctx.createGain();
        o.type = type; o.frequency.setValueAtTime(fr, t); o.frequency.linearRampToValueAtTime(fr * 0.75, t + 0.7);
        lfo.frequency.value = 27; lg.gain.value = fr * 0.15;         // rough, rattling throat
        lfo.connect(lg).connect(o.frequency);
        o.connect(f); o.start(t); o.stop(t + 0.8); lfo.start(t); lfo.stop(t + 0.8);
      }
      noise(t, 0.65, { freq: 900, q: 1, vol: 0.12, attack: 0.1 });
      return 0.8;
    },
    hiss(t) {                                           // sssss with a little tongue flutter
      noise(t, 0.8, { type: "highpass", freq: 4500, vol: 0.25, attack: 0.08 });
      noise(t + 0.1, 0.6, { freq: 6500, q: 3, vol: 0.1, attack: 0.1 });
      return 0.8;
    },
    pop(t) {
      tone(t, 300, 0.12, { to: 900, vol: 0.4 });
      tone(t + 0.13, 500, 0.12, { to: 1400, vol: 0.3 });
      return 0.3;
    },
    none() { return 0; },
    robot(t) {                                          // name tags: little printer robot
      [988, 1319, 784, 1175, 1568, 1047].forEach((f, i) => tone(t + i * 0.08, f, 0.07, { type: "square", vol: 0.08 }));
      return 0.55;
    },
    kaching(t) {                                        // till drawer + bell
      noise(t, 0.05, { freq: 3000, q: 2, vol: 0.4 });
      noise(t + 0.06, 0.08, { freq: 1500, q: 2, vol: 0.3 });
      bell(t + 0.12, 2093, 1.2, 0.3); bell(t + 0.12, 2637, 1.2, 0.2);
      return 1.0;
    },
    fanfare(t) {                                        // ta-ta-ta-taaa
      [[523, 0, 0.14], [659, 0.15, 0.14], [784, 0.3, 0.14], [1047, 0.45, 0.6]].forEach(([f, at, d]) => {
        tone(t + at, f, d, { type: "triangle", vol: 0.35, attack: 0.01 });
        tone(t + at, f * 2, d, { type: "square", vol: 0.04, attack: 0.01 });
      });
      return 1.1;
    },
    // printer alerts
    plateDone(t) { [1047, 1319, 1568, 2093].forEach((f, i) => bell(t + i * 0.16, f, 1.0, 0.3)); return 1.4; },
    colorChange(t) { for (let i = 0; i < 3; i++) { bell(t + i * 0.5, 1760, 0.4, 0.35); bell(t + i * 0.5 + 0.2, 1319, 0.4, 0.35); } return 1.5; },
    error(t) {
      for (let i = 0; i < 4; i++) tone(t + i * 0.3, i % 2 ? 330 : 440, 0.28, { type: "square", vol: 0.18, attack: 0.01 });
      return 1.2;
    },
    newOrder(t) { bell(t, 1568, 0.6, 0.18); return 0.4; },
  };

  // play names one after another
  function play(...names) {
    if (enabled && !muted) force(...names);
  }
  function force(...names) {                          // also when muted (▶ test in the settings)
    try {
      audio();
      let t = ctx.currentTime + 0.05;
      for (const n of names) t += (SOUNDS[n] || SOUNDS.bells)(t) + 0.08;
    } catch { /* no audio device: stay silent */ }
  }

  // a finished sale (each item already made its sound when tapped): the order's
  // name tags beep, ka-ching, fanfare for a big basket
  function sale(withOrder, totalCents, count) {
    play(...(withOrder ? ["robot"] : []), "kaching", ...(totalCents >= 2000 || count >= 5 ? ["fanfare"] : []));
  }

  return {
    play, force, sale, NAMES: ["bells", "crunch", "zap", "roar", "hiss", "pop", "none"],
    LABELS: { bells: "🔔 Glöckchen", crunch: "🍪 Knusper", zap: "⚡ Blitz", roar: "🐉 Brüllen",
      hiss: "🐍 Zischen", pop: "🫧 Plopp", none: "🔇 kein Ton" },
    setEnabled(on) { enabled = on; },
    get muted() { return muted; },
    setMuted(m) { muted = m; try { localStorage.setItem("staffMute", m ? "1" : "0"); } catch { /* ignore */ } },
  };
})();
