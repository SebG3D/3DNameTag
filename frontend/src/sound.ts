// Kiosk sounds, synthesized with WebAudio (no files). Every letter is a note of a
// pentatonic scale, so typing a name plays its own little tune that never sounds
// wrong; after ordering the name is played back with a jingle. Silent if audio is
// unavailable or the staff switched kiosk sounds off.
let ctx: AudioContext | null = null;
let out: GainNode | null = null;
let enabled = true;

export const setSound = (on: boolean) => { enabled = on; };

function audio(): AudioContext | null {
  if (!enabled) return null;
  try {
    if (!ctx) {
      ctx = new AudioContext();
      // the display speaker is USB-powered: long loud sounds made the screen drop out,
      // so keep the level moderate and limit peaks
      const comp = ctx.createDynamicsCompressor();
      comp.threshold.value = -18; comp.ratio.value = 8;
      out = ctx.createGain();
      out.gain.value = 0.5;
      out.connect(comp).connect(ctx.destination);
    }
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  } catch {
    enabled = false;
    return null;
  }
}

function tone(c: AudioContext, t: number, freq: number, dur: number, vol: number,
  type: OscillatorType = "sine", to?: number): void {
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = type;
  o.frequency.setValueAtTime(freq, t);
  if (to) o.frequency.exponentialRampToValueAtTime(to, t + dur);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(vol, t + 0.004);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g).connect(out!);
  o.start(t);
  o.stop(t + dur + 0.02);
}

// soft marimba: sine plus a short bright overtone
function mallet(c: AudioContext, t: number, freq: number, vol = 0.22, dur = 0.35): void {
  tone(c, t, freq, dur, vol);
  tone(c, t, freq * 4, 0.06, vol * 0.25);
}

// C major pentatonic, C5 .. E7 (12 steps)
const SCALE = [523, 587, 659, 784, 880, 1047, 1175, 1319, 1568, 1760, 2093, 2349];
const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const UMLAUT: Record<string, string> = { Ä: "A", Ö: "O", Ü: "U", ß: "S" };

/** pitch of one character, null for space/dash (a rest) */
function pitch(ch: string): number | null {
  const k = UMLAUT[ch] ?? ch;
  const i = LETTERS.indexOf(k);
  if (i >= 0) return SCALE[i % SCALE.length];
  if (k >= "0" && k <= "9") return SCALE[Number(k) % SCALE.length];
  return null;
}

/** a key on the on-screen keyboard: the letter's note (space: a soft tick) */
export function key(ch: string): void {
  const c = audio();
  if (!c) return;
  const p = pitch(ch);
  if (p) mallet(c, c.currentTime, p);
  else tone(c, c.currentTime, 300, 0.06, 0.1, "triangle");
}

/** backspace: a little falling blip */
export function back(): void {
  const c = audio();
  if (!c) return;
  tone(c, c.currentTime, 700, 0.1, 0.14, "triangle", 300);
}

/** a choice (colour, font, shape): rising pop, a bit higher for later items */
export function pop(i = 0): void {
  const c = audio();
  if (!c) return;
  const f = SCALE[(i * 2) % 8];
  tone(c, c.currentTime, f / 2, 0.12, 0.25, "sine", f * 1.2);
}

/** order sent: play the names as a tune, then a jingle */
export function celebrate(names: string[]): void {
  const c = audio();
  if (!c) return;
  let t = c.currentTime + 0.1;
  for (const ch of names.join(" ").slice(0, 24)) {
    const p = pitch(ch);
    if (p) mallet(c, t, p, 0.24, 0.3);
    t += p ? 0.15 : 0.12;
  }
  t += 0.1;
  // jingle: arpeggio up + sparkle chord
  [1047, 1319, 1568, 2093].forEach((f, i) => mallet(c, t + i * 0.09, f, 0.22, 0.5));
  [2093, 2637, 3136].forEach((f) => tone(c, t + 0.45, f, 1.0, 0.08));
}
