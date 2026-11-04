import { useEffect, useRef } from "react";
import { click } from "../sound";

const ROWS = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-"],
  ["Q", "W", "E", "R", "T", "Z", "U", "I", "O", "P", "Ü"],
  ["A", "S", "D", "F", "G", "H", "J", "K", "L", "Ö", "Ä"],
  ["Y", "X", "C", "V", "B", "N", "M", "ß"],
];

/** QWERTZ capitals only. Backspace repeats when held (400 ms, then 80 ms). */
export function Keyboard({ onKey, onBackspace }: { onKey: (k: string) => void; onBackspace: () => void }) {
  const rep = useRef<{ t?: number; i?: number }>({});
  const back = useRef(onBackspace);
  back.current = onBackspace;
  const stop = () => {
    clearTimeout(rep.current.t);
    clearInterval(rep.current.i);
  };
  useEffect(() => stop, []);
  const startBack = () => {
    stop();
    click();
    back.current();
    rep.current.t = window.setTimeout(() => {
      rep.current.i = window.setInterval(() => back.current(), 80);
    }, 400);
  };
  const press = (k: string) => (e: React.PointerEvent) => {
    e.preventDefault();
    click();
    onKey(k);
  };
  return (
    <div className="kbd">
      {ROWS.map((row, i) => (
        <div key={i} className="kbd-row">
          {row.map((k) => (
            <button key={k} className="key" onPointerDown={press(k)}>{k}</button>
          ))}
          {i === 3 && (
            <button className="key key-back" aria-label="Löschen"
              onPointerDown={(e) => { e.preventDefault(); startBack(); }}
              onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop}>⌫</button>
          )}
        </div>
      ))}
      <div className="kbd-row">
        <button className="key key-space" onPointerDown={press(" ")}>Leertaste</button>
      </div>
    </div>
  );
}
