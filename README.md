# ERG-Training

Steuerung eines Bluetooth-Smart-Trainers direkt vom Linux-Rechner – mit Workouts in % der FTP,
ERG-Modus, TSS/CTL-Auswertung und einem kleinen Fenster, das immer im Vordergrund bleibt
(z. B. zum Fahren während der Arbeit).

*English summary: a small Linux desktop app (Python/Tk) to control a Bluetooth FTMS smart trainer
(tested with a Wahoo KICKR) in ERG mode, with a built-in library of FTP-based workouts, `.zwo`/`.mrc`
import, TSS/CTL/ATL/TSB tracking, TCX export and an always-on-top mini window. UI is in German.*

## Funktionen

- **Verbindung per Bluetooth (FTMS)** – dem offenen Standard, den fast alle aktuellen Smart-Trainer
  sprechen. Getestet mit einer Wahoo KICKR.
- **ERG-Modus**: Die Rolle hält die vorgegebene Leistung, unabhängig von Trittfrequenz und Gang.
- **Workout-Bibliothek** (60+ Einheiten), gegliedert nach Trainingsbereichen:
  Standard · Tests · Regeneration · Ausdauer · Tempo · Sweet Spot · Schwelle · VO2max.
  Alle Werte in % der FTP; zu jedem Workout werden Dauer, geschätzte TSS und IF angezeigt.
- **FTP-Tests** (Rampentest, 20-min-Test, 2 × 8 min) mit automatischem FTP-Vorschlag.
- **Eigene Workouts** im Format `.zwo` (Zwift), `.mrc` (ErgDB/TrainerDay/GoldenCheetah) oder `.erg`
  – einfach in den Ordner `workouts/` legen.
- **Mini-Fenster** (Taste `m`): Ziel-/Ist-Watt, Trittfrequenz, Restzeit, Profil – immer im Vordergrund.
- **Auswertung**: NP, IF, TSS je Fahrt sowie Fitness (CTL), Ermüdung (ATL) und Form (TSB).
- **Aufzeichnung** jeder Fahrt als `.tcx` (lässt sich z. B. bei Strava oder intervals.icu hochladen).
- **Mini-Fenster durchsichtig**: Mausrad über dem Fenster stellt die Deckkraft ein (30–100 %).
- Zeit läuft nur, solange getreten wird (Auto-Pause); Signalton bei Intervallwechsel.

## Installation (Ubuntu / Linux)

Voraussetzungen: Python ≥ 3.10 mit Tk (`sudo apt install python3-tk python3-venv`), Bluetooth (BlueZ).

```sh
git clone https://github.com/pfaffelh/rolle.git
cd rolle
./start.sh              # legt beim ersten Start eine virtuelle Umgebung an und installiert 'bleak'
./install-desktop.sh    # optional: Eintrag im Programmmenü und Symbol im GNOME-Dock
```

## Benutzung

1. **Andere Apps trennen** (z. B. die Trainings-App am Handy schließen) – die Rolle nimmt meist nur
   eine Bluetooth-Verbindung gleichzeitig an. Kurz treten, damit die Rolle aufwacht.
2. **Suchen** → Rolle wird gefunden und (bei nur einer Rolle) automatisch verbunden.
3. **FTP** oben eintragen.
4. **Kategorie** und **Workout** wählen → **▶ Start** → lostreten.
5. Mit `m` ins Mini-Fenster wechseln.

| Taste | Funktion |
|---|---|
| Leertaste | Start / Pause |
| ↑ / ↓ | Intensität ±1 % (ohne laufendes Workout: ERG ±5 W) |
| m | Mini-Fenster an/aus |

Am Ende eines Workouts wird die Fahrt in `fahrten/` gespeichert und in `verlauf.json` eingetragen
(Grundlage für CTL/ATL/TSB). Persönliche Daten (`einstellungen.json`, `verlauf.json`, `fahrten/`)
werden nicht ins Repository übernommen.

## Eigene Workouts in Python

Neue Einheiten lassen sich in `workouts.py` in der Funktion `bibliothek()` ergänzen, z. B.

```python
add("Sweet Spot", "Sweet Spot 3 × 12 min", "3 × 12 min bei 90 %, 5 min locker.",
    einfahren(10) + intervalle(3, M(12), 0.90, M(5), 0.55, "Sweet Spot") + ausfahren(8))
```

## Dateien

| Datei | Inhalt |
|---|---|
| `training.py` | Programm (Oberfläche, Workout-Ablauf, Aufzeichnung) |
| `ftms.py` | Bluetooth-FTMS-Anbindung (bleak) |
| `workouts.py` | Workout-Bibliothek und Import von `.zwo`/`.mrc`/`.erg` |
| `metriken.py` | NP, IF, TSS, CTL/ATL/TSB |
| `scan.py` | Diagnose: listet Bluetooth-Geräte in der Nähe |

## Fehlersuche

- **Rolle wird nicht gefunden:** Ist noch ein Handy/eine App verbunden? `python scan.py` zeigt alle
  Bluetooth-Geräte; die Rolle sollte mit „FTMS“ markiert sein.
- **Verbindung bricht beim ersten Versuch ab:** Das Programm versucht es automatisch dreimal.

## Hinweis

Die Werte für TSS & Co. folgen den üblichen Formeln (Coggan). Die Workouts sind Vorschläge und
ersetzen keine Trainingsplanung. Training auf eigene Verantwortung.
