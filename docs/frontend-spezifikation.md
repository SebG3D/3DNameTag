# Frontend-Spezifikation: Kiosk-App „Namens-Anhänger-Drucker"

Basis für die Implementierung. Zielgruppe der UI: Kinder ca. 5–14 Jahre, Bedienung ohne Hilfe. Läuft im Chromium-Kiosk-Modus auf einem Raspberry Pi 5 mit Touchscreen (10–15", 1280×800 oder 1920×1080, Landscape).

---

## 1. Technologie-Entscheidungen

| Bereich | Wahl | Begründung |
|---|---|---|
| Framework | **React 18 + Vite** | Komponentenstruktur für Screens/Keyboard; Vite-Build wird statisch von FastAPI ausgeliefert (`/static`). Alternative: Preact, falls Pi-Performance knapp wird |
| 3D-Vorschau | **Three.js** (+ `STLLoader` aus three/examples) | Server-STL anzeigen; Live-Vorschau per `ExtrudeGeometry` |
| Font-Handling (Vorschau) | **opentype.js** | Textumriss → Shape → Extrude, rein clientseitig, nur für die Live-Vorschau |
| State | React `useReducer` + Context | Ein globaler Wizard-State, keine externe Lib nötig |
| Styling | Plain CSS / CSS-Module | Kein Tailwind-Build nötig; große Custom-Properties für Theming |
| Kommunikation | `fetch` + Polling (2 s) | WebSocket optional später; Polling ist auf lokalem Ethernet völlig ausreichend und robuster |
| Sprache | Deutsch, alle Texte in `strings.ts` | Später leicht zweisprachig erweiterbar |

**Keine** Abhängigkeit von externen CDNs oder Internet — alle Assets (Fonts als .woff2, libs via npm) werden lokal gebundelt.

---

## 2. Screen-Flow (Wizard)

```
[0 Attract] → [1 Name] → [2 Schrift] → [3 Form] → [4 Farbe] → [5 Vorschau] → [6 Bestätigt/Queue] → zurück zu [0]
```

Globale Regeln:
- Jeder Screen: großer „Weiter"-Button unten rechts, „Zurück" unten links, Fortschrittsanzeige oben (Punkte 1–5)
- **Inaktivitäts-Timeout:** 90 s ohne Touch → Abbruch-Dialog („Bist du noch da?", 15 s Countdown) → Reset auf Screen 0. Verhindert halbfertige Sessions
- Kein Browser-Zoom, kein Kontextmenü, kein Textselektieren (CSS `user-select: none`, `touch-action: manipulation`)
- Alle Touch-Ziele **min. 64×64 px**, Abstand min. 12 px

### Screen 0 — Attract / Idle
- Vollbild-Animation: langsam rotierender Beispiel-Anhänger (Three.js), großer pulsierender Button **„Tippe hier und mach deinen Anhänger!"**
- Unten dezente Statuszeile: Druckerstatus + aktuelle Warteschlange („Gerade druckt: LEON · 3 warten")
- Wenn Warteschlange voll (siehe §6): Button ersetzt durch Hinweis „Warteschlange voll — komm in 30 Minuten wieder 🙂"

### Screen 1 — Name eingeben
- Große Anzeige des getippten Namens (min. 72 px Schrifthöhe) mit blinkendem Cursor
- **Eigene On-Screen-Tastatur** (siehe §3) — die OS-Tastatur wird nie verwendet
- Live-Validierung: erlaubt `A–Z Ä Ö Ü ß 0–9 Leerzeichen Bindestrich`, max. 12 Zeichen. Zähler „8/12" sichtbar. Bei vollem Feld wackelt die Anzeige kurz (CSS-Animation), kein Fehlertext nötig
- „Weiter" erst aktiv ab 1 Zeichen (nach Trim)

### Screen 2 — Schrift wählen
- Grid 2×3 mit 6 Font-Karten. Jede Karte rendert **den eingegebenen Namen live in der jeweiligen Schrift** (Web-Font lokal geladen) — nicht nur den Fontnamen
- Auswahl = dicker farbiger Rahmen + Häkchen
- Font-Liste (muss 1:1 mit den auf dem Pi installierten TTFs und den OpenSCAD-Fontstrings übereinstimmen, gepflegt in `fonts.ts`):

| ID | Anzeige | OpenSCAD-String |
|---|---|---|
| baloo | Baloo 2 | `Baloo 2:style=Bold` |
| bangers | Bangers | `Bangers:style=Regular` |
| fredoka | Fredoka | `Fredoka:style=SemiBold` |
| pacifico | Pacifico | `Pacifico:style=Regular` |
| titan | Titan One | `Titan One:style=Regular` |
| chewy | Chewy | `Chewy:style=Regular` |

### Screen 3 — Form wählen
- 3 große Karten mit Icon/Render: **Tag (Stadium)**, **Herz**, **Knochen**
- IDs `stadium | heart | bone` — identisch zu den `shape`-Werten im .scad-Template

### Screen 4 — Textfarbe wählen
- Hinweistext: „Die Grundfarbe ist heute **[Grundfarbe des Tages]** — such dir die Farbe für deinen Namen aus!"
- 4–6 Farbkreise (entsprechend den am Stand vorhandenen Filamentrollen), konfiguriert in `config.json` (siehe §7), damit der Betreuer sie morgens ohne Code-Änderung anpassen kann
- Die Farbwahl wird **nicht** an den Slicer übergeben (M600 ist farbunabhängig) — sie erscheint nur als Anweisung auf der Admin-Seite („Job #12: Text in ROT")

### Screen 5 — Vorschau & Bestätigen
1. Beim Betreten: `POST /api/jobs/preview` → Server rendert echte STL → Anzeige via STLLoader (drehbar per Touch-Drag, OrbitControls mit deaktiviertem Zoom/Pan)
2. Während des Renders (5–15 s): die clientseitige Live-Vorschau (ExtrudeGeometry) bleibt sichtbar, überlagert mit Spinner „Wird gebaut…" — kein leerer Screen
3. Anzeige: Name, Schrift, Form, Farbchip, geschätzte Druckzeit (vom Server aus dem Slicing: `estimated_min`)
4. Buttons: **„Drucken!"** (groß, grün) und „Nochmal ändern" (zurück zu Screen 1, State bleibt erhalten)

### Screen 6 — Bestätigt
- Große Erfolgsanimation (Konfetti, CSS oder canvas-confetti lokal gebundelt)
- **Abhol-Info:** „Du bist Nummer **7**! Fertig ungefähr um **14:35**. Merk dir deine Nummer!" — Nummer riesig darstellen
- Optional: Hinweis „Sag am Stand deine Nummer" (kein Ausdruck, keine E-Mail — bewusst simpel)
- Auto-Reset nach 20 s oder Button „Fertig"

---

## 3. On-Screen-Tastatur (eigene Komponente)

- QWERTZ-Layout, 3 Reihen + Leertaste/Backspace-Reihe; Umlaute Ä Ö Ü als eigene Tasten, ß neben Backspace
- Nur Großbuchstaben (Tags werden ohnehin in Caps gedruckt → keine Shift-Taste, weniger Komplexität)
- Zahlenreihe 0–9 oben, Bindestrich-Taste
- Tasten: min. 64×64 px, `touchstart`-Feedback (Taste vergrößert sich kurz, dezenter Klick-Sound via WebAudio, lokal)
- Backspace mit Repeat bei Halten (400 ms Delay, dann 80 ms Intervall)
- Implementierung als reine React-Komponente `<KioskKeyboard onKey={...} onBackspace={...} />`, kein externes Paket

---

## 4. 3D-Vorschau im Detail

**Live-Vorschau (Screens 2–5, approximativ):**
1. `opentype.js` lädt die gewählte .woff2/.ttf, `font.getPath(name)` → SVG-Pfadkommandos
2. Konvertierung zu `THREE.Shape` (Bibliotheksfunktion `SVGLoader.createShapes` oder eigener Path-Parser)
3. `ExtrudeGeometry` (Text, Höhe 1.2) auf einer Basisplatte (`ExtrudeGeometry` des Umrisses, Höhe 2.4). Umriss vereinfacht als gerundetes Rechteck um die Text-BoundingBox — muss nicht exakt dem OpenSCAD-`hull()` entsprechen, nur ähnlich aussehen
4. Zwei Materialien: Basis in Grundfarbe des Tages, Text in gewählter Farbe → Kinder sehen sofort den Zweifarb-Effekt

**Echte Vorschau (Screen 5):** STL vom Server via `STLLoader`; einfärben analog geht bei einer STL nicht pro Teil → Lösung: Server liefert **zwei STLs** (`base.stl`, `text.stl`, OpenSCAD rendert beide Teile getrennt mit demselben Template), Frontend lädt beide und färbt sie separat. (Gedruckt wird die kombinierte Datei; die Trennung ist nur für die Vorschau.)

**Performance auf dem Pi:** `renderer.setPixelRatio(1)`, Antialias aus, ein einziges `WebGLRenderer`-Objekt app-weit wiederverwenden (Canvas wird zwischen Screens umgehängt), `frameloop` pausieren wenn nichts animiert.

---

## 5. API-Kontrakt (Frontend ↔ FastAPI)

Alle Antworten JSON. Fehler: `{ "error": "code", "message": "…" }` mit HTTP 4xx/5xx.

```
GET  /api/config
→ { "base_color": {"name":"Blau","hex":"#1565C0"},
    "text_colors":[{"id":"red","name":"Rot","hex":"#E53935"},…],
    "fonts":[{"id":"baloo","label":"Baloo 2"},…],
    "shapes":["stadium","heart","bone"],
    "queue_limit": 12 }

POST /api/jobs/preview
Body: { "name":"EMMA","font":"baloo","shape":"stadium" }
→ { "preview_id":"p_8f2a",
    "stl_base_url":"/files/p_8f2a_base.stl",
    "stl_text_url":"/files/p_8f2a_text.stl",
    "estimated_min": 11 }
(Server: OpenSCAD-Render + Test-Slice; 5–15 s → Frontend zeigt Spinner)

POST /api/jobs
Body: { "preview_id":"p_8f2a","text_color":"red" }
→ { "job_id": 7, "queue_position": 3, "eta":"14:35" }

GET  /api/status          (Polling alle 2 s auf Screen 0 und 6)
→ { "printer":"printing|idle|attention|offline",
    "current_job": {"id":6,"name":"LEON","remaining_min":4} | null,
    "queue_length": 3, "queue_full": false }
```

Frontend-Regeln:
- `name` vor dem Senden clientseitig validieren (gleiche Whitelist wie Server) — Server validiert trotzdem nochmal (Frontend-Validierung ist UX, Server-Validierung ist Sicherheit)
- Bei `printer: "offline"` oder Netzwerkfehler: freundlicher Vollbild-Hinweis „Kleine Pause — der Drucker macht gerade Pause. Hol bitte einen Erwachsenen 🙂" + Auto-Retry alle 5 s
- `preview_id` verfällt serverseitig nach 10 min (Timeout-Sessions erzeugen keine Waisen-Jobs)

---

## 6. State-Modell

```ts
type WizardState = {
  screen: 0|1|2|3|4|5|6;
  name: string;              // roh, uppercase, max 12
  fontId: string | null;
  shape: "stadium"|"heart"|"bone" | null;
  textColorId: string | null;
  preview: { id: string; baseUrl: string; textUrl: string; etaMin: number } | null;
  job: { id: number; position: number; eta: string } | null;
};
```

- Ein Reducer, Aktionen: `KEY_PRESS, BACKSPACE, SET_FONT, SET_SHAPE, SET_COLOR, PREVIEW_OK, PREVIEW_FAIL, CONFIRM_OK, RESET, TIMEOUT`
- `RESET` setzt alles auf Initial + Screen 0; wird von Timeout, „Fertig" und Fehlerdialog-Abbruch benutzt
- Config (`GET /api/config`) einmal beim App-Start laden, in Context halten; bei Fehlschlag Retry-Screen

---

## 7. Konfigurierbarkeit ohne Code (config.json auf dem Pi)

Vom Backend gelesen und via `/api/config` ausgeliefert:
- Grundfarbe des Tages (Name + Hex)
- Verfügbare Textfarben (= eingelegte/vorhandene Filamentrollen)
- Queue-Limit (Standard 12 — bei ~11 min/Druck entspricht das ~2 h Wartezeit; mehr anzunehmen wäre unfair)
- Event-Name für den Attract-Screen (optional)

Betreuer-Workflow morgens: config.json anpassen → Backend-Service neu starten → fertig.

---

## 8. Visuelles Design

- **Stimmung:** bunt, freundlich, große Formen — aber nicht chaotisch. Eine Akzentfarbe pro Screen-Schritt (Fortschrittspunkte in Regenbogenfolge) schafft Orientierung
- **Typo:** UI-Font „Fredoka" oder „Baloo 2" (ohnehin gebundelt), Grundgröße 24 px, Buttons 28–32 px, Namensanzeige 72 px+
- **Buttons:** abgerundet (radius 16–24 px), kräftige Füllfarben, deutlicher Pressed-State (Scale 0.96 + dunklerer Ton). Primäraktion immer grün, unten rechts; Zurück immer neutral-grau, unten links — Positionen nie tauschen
- **Kontrast:** WCAG AA auch bei Sonneneinstrahlung am Stand — keine hellgrauen Texte, kräftige Farben auf Weiß
- **Animationen:** kurz (150–250 ms), nur Feedback (Tastendruck, Kartenwahl, Screenwechsel-Slide). Konfetti nur auf Screen 6
- Alles offline: Fonts als .woff2 im Bundle, keine Webfont-CDNs

---

## 9. Kiosk-Härtung (Frontend-Anteil)

- `contextmenu`, `dblclick`-Zoom, Pinch: unterbunden (`touch-action`, Event-preventDefault)
- Kein sichtbarer Scroll: jede Screen-Ansicht passt in den Viewport (Layout mit `100dvh`, Grid)
- Vollbild-Wache: `document.fullscreenElement`-Check ist im Kiosk-Chromium unnötig (Flag `--kiosk`), aber App rendert defensiv auch bei ungewöhnlichen Viewports ab 1024×600
- Globaler `ErrorBoundary`: bei JS-Crash freundlicher Neustart-Screen + `location.reload()` nach 5 s
- Versteckter Admin-Zugang: 5× Tippen in die obere linke Ecke innerhalb 3 s → PIN-Dialog → öffnet `/admin` (für Notfälle direkt am Gerät; normal läuft Admin auf dem Handy)

---

## 10. Projektstruktur (Vorschlag)

```
frontend/
├─ src/
│  ├─ main.tsx, App.tsx            # Router = Wizard-Switch über state.screen
│  ├─ state/ (reducer.ts, types.ts, ConfigContext.tsx)
│  ├─ api/ (client.ts)             # fetch-Wrapper, Polling-Hook usePrinterStatus()
│  ├─ screens/ (Attract, Name, Font, Shape, Color, Preview, Done).tsx
│  ├─ components/
│  │  ├─ KioskKeyboard.tsx
│  │  ├─ ProgressDots.tsx, NavButtons.tsx, IdleGuard.tsx
│  │  └─ three/ (PreviewCanvas.tsx, useLiveTextMesh.ts, useStlPair.ts)
│  ├─ assets/fonts/*.woff2, sounds/click.mp3
│  └─ strings.ts, fonts.ts
├─ public/ (Icons, Beispiel-STL für Attract)
└─ vite.config.ts                  # base:'/static/', Build-Ziel = FastAPI static dir
```

---

## 11. Implementierungs-Reihenfolge (Meilensteine)

1. **M1:** Wizard-Gerüst mit allen Screens, State, Keyboard, Dummy-Daten — komplett ohne Backend testbar
2. **M2:** Live-Vorschau (opentype.js + Three.js) für Screens 2–5
3. **M3:** API-Anbindung (config, preview mit echten STL-Paaren, jobs, status-Polling) gegen das FastAPI-Backend
4. **M4:** Attract-Screen, IdleGuard, Fehler-/Offline-Zustände, Konfetti
5. **M5:** Kiosk-Härtung, Performance-Pass auf dem Pi (Pixelratio, Renderer-Reuse), Praxistest mit Kindern

## 12. Offene Fragen
- [ ] Herz/Knochen-Form: Name innerhalb der Form oder Form als Anhängsel neben dem Text? (beeinflusst .scad und Vorschau)
- [ ] Sound an/aus per config?
- [ ] Zweite Sprache (Englisch) nötig?
- [ ] Nummernvergabe: reiner Zähler pro Tag oder mit Namenskürzel („EMMA-07")?
