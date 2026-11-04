import type { Status } from "../api";
import { colorById, useConfig } from "../config";
import { TagSvg } from "../components/TagSvg";
import { useIcons } from "../icons";

export function statusLine(st: Status | null): string {
  if (!st) return "";
  const parts: string[] = [];
  const p = st.current_plate;
  if (p && (p.status === "printing" || p.status === "color_change")) {
    const names = p.names.slice(0, 4).join(", ") + (p.names.length > 4 ? " …" : "");
    parts.push(`Gerade druckt: ${names}`);
  }
  const waiting = st.queue_length - (p?.names.length ?? 0);
  if (waiting > 0) parts.push(`${waiting} ${waiting === 1 ? "Anhänger wartet" : "Anhänger warten"}`);
  return parts.join(" · ");
}

export function Attract({ status, onStart }: { status: Status | null; onStart: () => void }) {
  const cfg = useConfig();
  const icons = useIcons();
  const sample = icons[cfg.shapes[0]?.id];
  const full = status?.queue_full;
  return (
    <div className="screen attract">
      <div className="event">{cfg.event_name}</div>
      <div className="attract-tag">
        {sample && <TagSvg outline={sample.outline} text={sample.text} baseHex={cfg.base_color.hex}
          textHex={colorById(cfg, "red").hex} className="sway" />}
      </div>
      {full ? (
        <div className="full-note">Gerade sind ganz viele Anhänger in der Warteschlange.<br />Komm bitte etwas später wieder 🙂</div>
      ) : (
        <button className="btn btn-go btn-huge pulse" onClick={onStart}>Tippe hier und mach deinen Anhänger!</button>
      )}
      <div className="status-line">{statusLine(status)}</div>
    </div>
  );
}
