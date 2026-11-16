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
      const comp = ctx.createDynamicsCompressor();      // several sounds at once must not clip
      out = ctx.createGain();
      out.gain.value = 0.8;
      out.connect(comp).connect(ctx.destination);
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

  // Game-Boy-like pulse wave (25 % duty): thin, bright, "8-bit"
  let pulse = null;
  function pulseWave() {
    if (!pulse) {
      const n = 32, re = new Float32Array(n), im = new Float32Array(n);
      for (let k = 1; k < n; k++) re[k] = (2 / (k * Math.PI)) * Math.sin(k * Math.PI * 0.25);
      pulse = ctx.createPeriodicWave(re, im);
    }
    return pulse;
  }
  function chip(t, freq, dur, vol = 0.12, vibrato = false) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.setPeriodicWave(pulseWave());
    o.frequency.setValueAtTime(freq, t);
    if (vibrato) {                                      // the long last note wobbles
      const lfo = ctx.createOscillator(), lg = ctx.createGain();
      lfo.frequency.value = 6; lg.gain.value = freq * 0.012;
      lfo.connect(lg).connect(o.frequency); lfo.start(t + 0.12); lfo.stop(t + dur);
    }
    g.gain.setValueAtTime(vol, t);
    g.gain.setValueAtTime(vol, t + dur * 0.8);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(out);
    o.start(t); o.stop(t + dur + 0.02);
  }

  // each returns its length in seconds, so a sale can play them one after another
  const SOUNDS = {
    bells(t) {                                          // sleigh bells + a bell
      for (let i = 0; i < 8; i++) noise(t + i * 0.09 + Math.random() * 0.02, 0.09, { type: "highpass", freq: 7000, vol: 0.22 });
      bell(t, 1319, 0.9, 0.2); bell(t + 0.18, 1568, 0.9, 0.2);
      return 0.9;
    },
    crunch(t) {                                         // a long bite into a crisp cookie
      // a crunch is many tiny, irregular cracks (grains), not a few puffs of noise
      const bite = (start, len, grains) => {
        for (let i = 0; i < grains; i++) {
          const at = start + Math.pow(Math.random(), 1.25) * len;          // a bit denser at the start
          noise(at, 0.004 + Math.random() * 0.018, {
            freq: 900 + Math.random() * 4500, q: 0.6 + Math.random() * 2,
            vol: 0.25 + Math.random() * 0.5, attack: 0.001 });
        }
        noise(start, 0.06, { type: "lowpass", freq: 600, vol: 0.35, attack: 0.002 });   // the "thud" of the teeth
      };
      bite(t, 0.45, 110);                               // one bite, twice as long, same density (no pause)
      return 0.5;
    },
    zap(t) {                                            // electric bzzzt: buzzing arc + sparks + snap
      const len = 0.6;
      const shape = ctx.createWaveShaper(), g = ctx.createGain();
      const curve = new Float32Array(256);
      for (let i = 0; i < 256; i++) { const x = i / 128 - 1; curve[i] = Math.tanh(x * 6); }
      shape.curve = curve;                              // hard clipping = harsh electric buzz
      g.gain.setValueAtTime(0.0001, t);
      // the arc flickers: random level every 20 ms
      for (let at = 0; at < len; at += 0.02) g.gain.setValueAtTime(0.08 + Math.random() * 0.22, t + at);
      g.gain.setValueAtTime(0.0001, t + len);
      shape.connect(g).connect(out);
      for (const fr of [110, 113.5, 220.7]) {
        const o = ctx.createOscillator();
        o.type = "sawtooth";
        o.frequency.setValueAtTime(fr, t);
        for (let at = 0.03; at < len; at += 0.03) o.frequency.setValueAtTime(fr * (0.92 + Math.random() * 0.16), t + at);
        o.connect(shape); o.start(t); o.stop(t + len + 0.02);
      }
      // sparks: short bright cracks scattered over the buzz
      for (let i = 0; i < 18; i++) {
        noise(t + Math.random() * len, 0.006 + Math.random() * 0.02,
          { type: "highpass", freq: 2500 + Math.random() * 4000, vol: 0.2 + Math.random() * 0.35, attack: 0.001 });
      }
      // final snap
      noise(t + len, 0.05, { type: "highpass", freq: 1500, vol: 0.6, attack: 0.001 });
      tone(t + len, 1800, 0.06, { type: "square", to: 400, vol: 0.12 });
      return len + 0.1;
    },
    caught(t) {                                         // "gotcha!": ball clicks shut, then an 8-bit victory tune (our own melody)
      noise(t, 0.03, { type: "highpass", freq: 2000, vol: 0.5, attack: 0.001 });
      chip(t, 1568, 0.04, 0.1); chip(t + 0.05, 2093, 0.05, 0.1);
      const s = t + 0.25, b = 0.11;                     // one beat step
      const N = { G4: 392, A4: 440, C5: 523, D5: 587, E5: 659, F5: 698, G5: 784, A5: 880, C6: 1047, C3: 131, F3: 175, G3: 196 };
      // melody: [note, start step, length steps]
      [["C5", 0, 1], ["E5", 1, 1], ["G5", 2, 1], ["C6", 3, 2],
       ["A5", 5, 1], ["G5", 6, 1], ["F5", 7, 1], ["A5", 8, 1], ["G5", 9, 1], ["E5", 10, 1],
       ["D5", 11, 1], ["G5", 12, 1], ["C6", 13, 6]].forEach(([n, at, len]) =>
        chip(s + at * b, N[n], len * b * 0.92, 0.13, len >= 6));
      // bass + harmony (second voice, softer)
      [["C3", 0, 4], ["F3", 5, 3], ["G3", 9, 3], ["C3", 13, 6]].forEach(([n, at, len]) =>
        tone(s + at * b, N[n], len * b, { type: "triangle", vol: 0.25, attack: 0.01 }));
      [["E5", 13, 6], ["G4", 13, 6]].forEach(([n, at, len]) => chip(s + at * b, N[n], len * b * 0.92, 0.05));
      return 0.25 + 19 * b + 0.1;
    },
    roar(t) {                                           // low growl, swelling and falling
      const f = ctx.createBiquadFilter(), g = ctx.createGain();
      f.type = "lowpass"; f.Q.value = 6;
      f.frequency.setValueAtTime(250, t); f.frequency.linearRampToValueAtTime(900, t + 0.35);
      f.frequency.exponentialRampToValueAtTime(200, t + 1.1);
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.6, t + 0.2);
      g.gain.setValueAtTime(0.6, t + 0.6); g.gain.exponentialRampToValueAtTime(0.0001, t + 1.15);
      f.connect(g).connect(out);
      for (const [fr, type] of [[82, "sawtooth"], [87, "sawtooth"], [123, "square"]]) {
        const o = ctx.createOscillator(), lfo = ctx.createOscillator(), lg = ctx.createGain();
        o.type = type; o.frequency.setValueAtTime(fr, t); o.frequency.linearRampToValueAtTime(fr * 0.7, t + 1.1);
        lfo.frequency.value = 23; lg.gain.value = fr * 0.15;         // rough, rattling throat
        lfo.connect(lg).connect(o.frequency);
        o.connect(f); o.start(t); o.stop(t + 1.2); lfo.start(t); lfo.stop(t + 1.2);
      }
      noise(t, 1.0, { type: "lowpass", freq: 700, vol: 0.25, attack: 0.15 });
      return 1.2;
    },
    hiss(t) {                                           // sssss with a little tongue flutter
      noise(t, 1.0, { type: "highpass", freq: 4500, vol: 0.35, attack: 0.08 });
      noise(t + 0.1, 0.8, { freq: 6500, q: 3, vol: 0.15, attack: 0.1 });
      return 1.0;
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
    play, force, sale, NAMES: ["bells", "crunch", "caught", "zap", "roar", "hiss", "pop", "none"],
    LABELS: { bells: "🔔 Glöckchen", crunch: "🍪 Knusper", caught: "🎉 Gefangen!", zap: "⚡ Blitz", roar: "🐉 Brüllen",
      hiss: "🐍 Zischen", pop: "🫧 Plopp", none: "🔇 kein Ton" },
    setEnabled(on) { enabled = on; },
    get muted() { return muted; },
    setMuted(m) { muted = m; try { localStorage.setItem("staffMute", m ? "1" : "0"); } catch { /* ignore */ } },
  };
})();
