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

  // 8-bit lead: square wave, softened by a lowpass (raw pulse waves are harsh on the
  // small display speaker), short attack so notes don't click
  function chip(t, freq, dur, vol = 0.1, vibrato = false, cutoff = 2800) {
    const o = ctx.createOscillator(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    o.type = "square";
    o.frequency.setValueAtTime(freq, t);
    if (vibrato) {
      const lfo = ctx.createOscillator(), lg = ctx.createGain();
      lfo.frequency.value = 5.5; lg.gain.value = freq * 0.008;
      lfo.connect(lg).connect(o.frequency); lfo.start(t + 0.15); lfo.stop(t + dur);
    }
    f.type = "lowpass"; f.frequency.value = cutoff; f.Q.value = 0.5;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(vol, t + 0.008);
    g.gain.linearRampToValueAtTime(vol * 0.75, t + Math.min(0.08, dur * 0.5));   // little pluck, then hold
    g.gain.setValueAtTime(vol * 0.75, t + dur * 0.85);
    g.gain.linearRampToValueAtTime(0.0001, t + dur);
    o.connect(f).connect(g).connect(out);
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
    caught(t) {                                         // "gotcha!": ball clicks shut, then an 8-bit victory fanfare (own melody)
      noise(t, 0.025, { type: "bandpass", freq: 2500, q: 1, vol: 0.4, attack: 0.001 });
      noise(t + 0.09, 0.025, { type: "bandpass", freq: 3200, q: 1, vol: 0.45, attack: 0.001 });
      const s = t + 0.3, b = 0.09;                      // one step = a sixteenth
      const N = { G4: 392, B4: 494, C5: 523, D5: 587, E5: 659, F5: 698, G5: 784, A5: 880, B5: 988, C6: 1047,
        C3: 131, F3: 175, G3: 196, C4: 262, E4: 330, A4: 440 };
      // lead [note, step, length]: run up, bounce, climb, big last note
      const lead = [["G4", 0, 1], ["C5", 1, 1], ["E5", 2, 1], ["G5", 3, 3], ["E5", 6, 1], ["G5", 7, 2],
        ["F5", 9, 1], ["A5", 10, 1], ["C6", 11, 3], ["A5", 14, 1],
        ["G5", 15, 1], ["B5", 16, 1], ["D5", 17, 1], ["C6", 18, 8]];
      lead.forEach(([n, at, len]) => chip(s + at * b, N[n], len * b, 0.1, len >= 8));
      // harmony a third/sixth below, quieter and darker
      [["E5", 3, 3], ["C5", 7, 2], ["F5", 11, 3], ["D5", 15, 3], ["E5", 18, 8]].forEach(([n, at, len]) =>
        chip(s + at * b, N[n], len * b, 0.045, false, 1800));
      // bass, soft triangle: C - F - G - C
      [["C3", 3, 6], ["F3", 9, 6], ["G3", 15, 3], ["C3", 18, 8]].forEach(([n, at, len]) =>
        tone(s + at * b, N[n], len * b, { type: "triangle", vol: 0.3, attack: 0.01 }));
      return 0.3 + 26 * b + 0.1;
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
    pop(t) {                                            // three bubbles, each a little different
      tone(t, 300, 0.12, { to: 900, vol: 0.4 });
      tone(t + 0.13, 500, 0.12, { to: 1400, vol: 0.3 });
      tone(t + 0.3, 380, 0.1, { to: 1150, vol: 0.32 });            // a bit higher, shorter
      tone(t + 0.42, 620, 0.09, { to: 1700, vol: 0.24 });
      tone(t + 0.6, 260, 0.16, { to: 1000, vol: 0.38 });           // last one lower and fatter
      tone(t + 0.76, 440, 0.14, { to: 1250, vol: 0.28 });
      return 0.95;
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
    plateDone(t) {                                      // rising bell chime, three times (hard to miss)
      for (let r = 0; r < 3; r++) {
        [1047, 1319, 1568, 2093].forEach((f, i) => bell(t + r * 1.4 + i * 0.16, f, 1.0, 0.3));
      }
      return 4.2;
    },
    colorChange(t) {                                    // ding-dong x9 (~4.5 s)
      for (let i = 0; i < 9; i++) { bell(t + i * 0.5, 1760, 0.4, 0.35); bell(t + i * 0.5 + 0.2, 1319, 0.4, 0.35); }
      return 4.5;
    },
    error(t) {                                          // spaceship red alert: rising whoop x4 over a low pulse
      const n = 4, len = 0.75;
      for (let i = 0; i < n; i++) {
        const at = t + i * (len + 0.12);
        const f = ctx.createBiquadFilter(), g = ctx.createGain();
        f.type = "lowpass"; f.frequency.value = 2200; f.Q.value = 1;
        g.gain.setValueAtTime(0.0001, at);
        g.gain.linearRampToValueAtTime(0.22, at + 0.05);
        g.gain.setValueAtTime(0.22, at + len - 0.12);
        g.gain.linearRampToValueAtTime(0.0001, at + len);
        f.connect(g).connect(out);
        for (const [type, mul] of [["sawtooth", 1], ["square", 1.005]]) {
          const o = ctx.createOscillator();
          o.type = type;
          o.frequency.setValueAtTime(380 * mul, at);
          o.frequency.exponentialRampToValueAtTime(950 * mul, at + len);
          o.connect(f); o.start(at); o.stop(at + len + 0.02);
        }
        tone(at, 110, len, { type: "square", vol: 0.12, attack: 0.02 });   // ominous low pulse
      }
      return n * (len + 0.12);
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
