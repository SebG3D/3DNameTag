import type { CSSProperties } from "react";

/** 2D tag from the backend SVG paths (mm, y down; the hole is a sub-path,
 *  so even-odd fill cuts it out). A small offset copy fakes the thickness. */

function bbox(d: string): [number, number, number, number] {
  const n = (d.match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/gi) ?? []).map(Number);
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i + 1 < n.length; i += 2) {
    x0 = Math.min(x0, n[i]); x1 = Math.max(x1, n[i]);
    y0 = Math.min(y0, n[i + 1]); y1 = Math.max(y1, n[i + 1]);
  }
  return isFinite(x0) ? [x0, y0, x1, y1] : [0, 0, 10, 10];
}

export function shade(hex: string, f: number): string {
  const v = parseInt(hex.replace("#", ""), 16);
  const ch = (s: number) => Math.max(0, Math.min(255, Math.round(((v >> s) & 255) * f)));
  return `rgb(${ch(16)},${ch(8)},${ch(0)})`;
}

type Props = {
  outline: string;
  text: string;
  baseHex: string;
  textHex: string;
  style?: CSSProperties;
  className?: string;
};

export function TagSvg({ outline, text, baseHex, textHex, style, className }: Props) {
  const [x0, y0, x1, y1] = bbox(outline);
  const pad = Math.max(x1 - x0, y1 - y0) * 0.04 + 1;
  const vb = `${x0 - pad} ${y0 - pad} ${x1 - x0 + 2 * pad + 1} ${y1 - y0 + 2 * pad + 1}`;
  return (
    <svg viewBox={vb} className={className} style={style} preserveAspectRatio="xMidYMid meet">
      <path d={outline} fill={shade(baseHex, 0.6)} fillRule="evenodd" transform="translate(0.9 0.9)" />
      <path d={outline} fill={baseHex} fillRule="evenodd" stroke="rgba(0,0,0,.25)" strokeWidth={0.25} />
      <path d={text} fill={shade(textHex, 0.55)} fillRule="evenodd" transform="translate(0.35 0.35)" />
      <path d={text} fill={textHex} fillRule="evenodd" stroke="rgba(0,0,0,.3)" strokeWidth={0.12} />
    </svg>
  );
}
