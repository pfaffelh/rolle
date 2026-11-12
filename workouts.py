"""Trainingseinheiten in % der FTP, gegliedert nach Trainingsbereichen.

Bereiche (nach Coggan, % FTP):
  Regeneration < 55 · Ausdauer 56–75 · Tempo 76–87 · Sweet Spot 88–94
  Schwelle 95–105 · VO2max 106–120+

Ein Workout ist eine Liste von Segmenten (Seg): dauer (s), start/ende (Anteil FTP), name, frei.
start == ende -> konstant, sonst Rampe. frei=True -> kein ERG (z. B. für Tests).

Eigene Workouts: .zwo-Dateien (Zwift-Format) nach workouts/ legen;
in einem Unterordner (z. B. workouts/VO2max/) landen sie in dieser Kategorie.
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

KATEGORIEN = ["Standard", "Tests", "Regeneration", "Ausdauer", "Tempo", "Sweet Spot", "Schwelle", "VO2max", "Eigene"]


@dataclass
class Seg:
    dauer: int
    start: float
    ende: float
    name: str = ""
    frei: bool = False

    def anteil(self, t: float) -> float:
        if self.dauer <= 0:
            return self.start
        return self.start + (self.ende - self.start) * min(1.0, max(0.0, t / self.dauer))


@dataclass
class Workout:
    name: str
    beschreibung: str
    segmente: list
    test: str = ""          # "rampe", "20min", "8min" -> Auswertung am Ende
    kategorie: str = "Eigene"
    absolut: bool = False   # True: start/ende sind feste Watt statt Anteile der FTP

    def als_ftp(self, ftp):
        """Für Workouts in festen Watt: Kopie mit Anteilen der aktuellen FTP (für Profil, TSS, Steuerung)."""
        if not self.absolut:
            return self
        w = Workout(self.name, self.beschreibung,
                    [Seg(s.dauer, s.start / ftp, s.ende / ftp, s.name, s.frei) for s in self.segmente],
                    self.test, self.kategorie)
        w.feste_watt = True
        return w

    @property
    def dauer(self):
        return sum(s.dauer for s in self.segmente)

    def plan_if_tss(self):
        """Geschätzte IF und TSS, wenn genau nach Plan gefahren wird."""
        a = []
        for s in self.segmente:
            a += [s.anteil(t + 0.5) for t in range(s.dauer)]
        if len(a) < 30:
            return 0.0, 0
        roll, summe = [], sum(a[:30])
        roll.append(summe / 30)
        for i in range(30, len(a)):
            summe += a[i] - a[i - 30]
            roll.append(summe / 30)
        if_ = (sum(r ** 4 for r in roll) / len(roll)) ** 0.25
        return round(if_, 2), round(len(a) / 3600 * if_ ** 2 * 100)


def M(minuten):
    return int(round(minuten * 60))


# --- Bausteine -----------------------------------------------------------------
def einfahren(minuten=10):
    return [Seg(M(minuten), 0.45, 0.72, "Einfahren")]


def einfahren_hart(minuten=10):
    """Einfahren plus kurze Aktivierung vor harten Intervallen."""
    return einfahren(minuten) + [Seg(60, 0.95, 0.95, "Aktivierung"), Seg(60, 0.55, 0.55, "locker"),
                                 Seg(60, 1.05, 1.05, "Aktivierung"), Seg(120, 0.55, 0.55, "locker")]


def ausfahren(minuten=8):
    return [Seg(M(minuten), 0.60, 0.40, "Ausfahren")]


def intervalle(n, an_s, an, aus_s, aus, name="Intervall"):
    out = []
    for i in range(n):
        out.append(Seg(an_s, an, an, f"{name} {i + 1}/{n}"))
        if aus_s and i < n - 1:
            out.append(Seg(aus_s, aus, aus, "Erholung"))
    return out


def saetze(n_saetze, n, an_s, an, aus_s, aus, pause_min, name):
    out = []
    for s in range(n_saetze):
        out += intervalle(n, an_s, an, aus_s, aus, f"{name} Satz {s + 1}/{n_saetze}")
        if s < n_saetze - 1:
            out.append(Seg(aus_s, aus, aus, "Erholung"))
            out.append(Seg(M(pause_min), 0.50, 0.50, "Satzpause"))
    return out


def pct(x):
    return f"{x * 100:.0f} %"


# --- Bibliothek ----------------------------------------------------------------
def bibliothek():
    W = []

    def add(kat, name, beschr, segs, test=""):
        W.append(Workout(name, beschr, segs, test=test, kategorie=kat))

    # ===== Standard (feste Watt) =====
    W.append(Workout("Standard 1 h · 75 % FTP",
                     "2,5 min Rampe auf 75 % FTP, 55 min konstant 75 % FTP, 2,5 min Rampe zurück.",
                     [Seg(150, 0.40, 0.75, "Rampe hoch"), Seg(M(55), 0.75, 0.75, "Konstant"),
                      Seg(150, 0.75, 0.40, "Rampe runter")], kategorie="Standard"))

    # ===== Tests =====
    rampe = [Seg(M(5), 0.45, 0.45, "Einfahren")]
    for i in range(30):
        p = 0.50 + 0.06 * i
        rampe.append(Seg(60, p, p, f"Stufe {i + 1} ({pct(p)})"))
    add("Tests", "Rampentest",
        "Jede Minute +6 % FTP bis zur Erschöpfung. Wenn es nicht mehr geht: aufhören und 'Beenden'. "
        "FTP ≈ 75 % der besten 1-Minuten-Leistung.", rampe, "rampe")
    add("Tests", "20-Minuten-FTP-Test",
        "Einfahren, 5 min hart, Erholung, dann 20 min so hart und gleichmäßig wie möglich – ohne ERG, "
        "Gänge selbst wählen. FTP ≈ 95 % des 20-min-Schnitts.",
        einfahren_hart(10) + [Seg(M(5), 1.05, 1.05, "5 min hart"), Seg(M(10), 0.5, 0.5, "Erholung"),
                              Seg(M(20), 1.0, 1.0, "20 min ALL-OUT (frei)", frei=True)] + ausfahren(10), "20min")
    add("Tests", "2 × 8-Minuten-Test",
        "Zwei maximale 8-min-Anstrengungen ohne ERG, 10 min Pause. FTP ≈ 90 % der besseren 8 Minuten.",
        einfahren_hart(12) + [Seg(M(8), 1.05, 1.05, "8 min ALL-OUT (frei)", frei=True),
                              Seg(M(10), 0.5, 0.5, "Erholung"),
                              Seg(M(8), 1.05, 1.05, "8 min ALL-OUT (frei)", frei=True)] + ausfahren(10), "8min")

    # ===== Regeneration (≤ 55 %) =====
    for m in (30, 45, 60):
        add("Regeneration", f"Regeneration {m} min", "Ganz locker bei 50 % FTP, hohe Trittfrequenz, nichts erzwingen.",
            [Seg(M(5), 0.40, 0.50, "Einrollen"), Seg(M(m - 10), 0.50, 0.50, "locker"), Seg(M(5), 0.50, 0.40, "Ausrollen")])
    add("Regeneration", "Regeneration mit Kadenz 45 min",
        "Locker bei 50 %, dazwischen 6 × 1 min bei 55 % mit sehr hoher Trittfrequenz (110+).",
        [Seg(M(8), 0.40, 0.50, "Einrollen")]
        + sum([[Seg(M(3), 0.50, 0.50, "locker"), Seg(60, 0.55, 0.55, f"Kadenz hoch {i + 1}/6")] for i in range(6)], [])
        + [Seg(M(8), 0.50, 0.50, "locker"), Seg(M(5), 0.50, 0.40, "Ausrollen")])

    # ===== Ausdauer (56–75 %) =====
    for m in (45, 60, 75, 90, 120, 150, 180):
        add("Ausdauer", f"Grundlage {m} min", "Gleichmäßig bei 65 % FTP (Zone 2).",
            einfahren(10) + [Seg(M(m - 15), 0.65, 0.65, "Grundlage")] + ausfahren(5))
    add("Ausdauer", "Grundlage progressiv 90 min", "Je 25 min bei 62 %, 67 % und 72 % FTP.",
        einfahren(10) + [Seg(M(25), 0.62, 0.62, "Grundlage 1/3"), Seg(M(25), 0.67, 0.67, "Grundlage 2/3"),
                         Seg(M(25), 0.72, 0.72, "Grundlage 3/3")] + ausfahren(5))
    add("Ausdauer", "Grundlage mit Tempospitzen 75 min",
        "Zone 2 mit 8 × 1 min bei 85 % alle 6 Minuten – hält die Beine wach.",
        einfahren(10) + sum([[Seg(M(5), 0.65, 0.65, "Grundlage"), Seg(60, 0.85, 0.85, f"Spitze {i + 1}/8")]
                             for i in range(8)], []) + [Seg(M(12), 0.65, 0.65, "Grundlage")] + ausfahren(5))
    add("Ausdauer", "Grundlage Kadenzpyramide 60 min",
        "65 % FTP konstant; Trittfrequenz alle 5 min wechseln: 85 – 95 – 105 – 95 – 85 …",
        einfahren(10) + [Seg(M(5), 0.65, 0.65, f"Kadenz {c}") for c in (85, 95, 105, 95, 85, 95, 105, 95, 85)]
        + ausfahren(5))

    # ===== Tempo (76–87 %) =====
    add("Tempo", "Tempo 3 × 10 min", "3 × 10 min bei 80 %, 5 min locker. Einstieg in Tempo.",
        einfahren(10) + intervalle(3, M(10), 0.80, M(5), 0.55, "Tempo") + ausfahren(8))
    add("Tempo", "Tempo 2 × 20 min", "2 × 20 min bei 80 %, 5 min locker.",
        einfahren(10) + intervalle(2, M(20), 0.80, M(5), 0.55, "Tempo") + ausfahren(8))
    add("Tempo", "Tempo 3 × 15 min", "3 × 15 min bei 82 %, 5 min locker.",
        einfahren(10) + intervalle(3, M(15), 0.82, M(5), 0.55, "Tempo") + ausfahren(8))
    add("Tempo", "Tempo 4 × 12 min", "4 × 12 min bei 85 %, 4 min locker.",
        einfahren(10) + intervalle(4, M(12), 0.85, M(4), 0.55, "Tempo") + ausfahren(8))
    add("Tempo", "Tempo 2 × 30 min", "2 × 30 min bei 78 %, 8 min locker.",
        einfahren(10) + intervalle(2, M(30), 0.78, M(8), 0.55, "Tempo") + ausfahren(8))
    add("Tempo", "Tempoblock 60 min", "60 min am Stück, ansteigend 76 → 84 %.",
        einfahren(10) + [Seg(M(60), 0.76, 0.84, "Tempoblock")] + ausfahren(8))

    # ===== Sweet Spot (88–94 %) =====
    for n, d, p, r in [(3, 10, 0.88, 5), (3, 12, 0.90, 5), (4, 10, 0.90, 4), (3, 15, 0.90, 5),
                       (2, 15, 0.92, 5), (2, 20, 0.90, 5), (4, 12, 0.90, 4), (3, 20, 0.90, 5), (2, 30, 0.88, 8)]:
        add("Sweet Spot", f"Sweet Spot {n} × {d} min", f"{n} × {d} min bei {pct(p)}, {r} min locker.",
            einfahren(10) + intervalle(n, M(d), p, M(r), 0.55, "Sweet Spot") + ausfahren(8))
    add("Sweet Spot", "Sweet Spot 1 × 45 min", "45 min am Stück bei 88 % – mentale Härte.",
        einfahren(12) + [Seg(M(45), 0.88, 0.88, "Sweet Spot")] + ausfahren(8))
    add("Sweet Spot", "Sweet Spot Pyramide 10-15-20-15-10",
        "Steigende und fallende Intervalle bei 90 %, 4 min locker.",
        einfahren(10) + sum([[Seg(M(d), 0.90, 0.90, f"Sweet Spot {d} min"), Seg(M(4), 0.55, 0.55, "Erholung")]
                             for d in (10, 15, 20, 15, 10)], [])[:-1] + ausfahren(8))
    ss_spitzen = []
    for s in range(3):
        for k in range(4):
            ss_spitzen += [Seg(150, 0.90, 0.90, f"Sweet Spot {s + 1}/3"), Seg(30, 1.20, 1.20, f"Spitze {s + 1}/3")]
        if s < 2:
            ss_spitzen.append(Seg(M(5), 0.55, 0.55, "Erholung"))
    add("Sweet Spot", "Sweet Spot mit Spitzen 3 × 12 min",
        "3 × 12 min bei 90 %, alle 3 min eine 30-s-Spitze bei 120 %.",
        einfahren(10) + ss_spitzen + ausfahren(8))

    # ===== Schwelle (95–105 %) =====
    for n, d, p, r in [(3, 8, 1.00, 4), (4, 8, 1.00, 4), (5, 6, 1.03, 3), (3, 10, 1.00, 5), (4, 10, 0.98, 5),
                       (3, 12, 0.97, 6), (2, 15, 0.98, 6), (2, 20, 0.95, 8), (3, 15, 0.96, 6)]:
        add("Schwelle", f"Schwelle {n} × {d} min", f"{n} × {d} min bei {pct(p)}, {r} min locker.",
            einfahren_hart(12) + intervalle(n, M(d), p, M(r), 0.55, "Schwelle") + ausfahren(10))
    add("Schwelle", "Schwelle 1 × 30 min", "30 min am Stück bei 95 %.",
        einfahren_hart(12) + [Seg(M(30), 0.95, 0.95, "Schwelle")] + ausfahren(10))

    def over_under(saetze_n, wdh, unter, ueber, unter_s, ueber_s):
        out = []
        for s in range(saetze_n):
            for k in range(wdh):
                out += [Seg(unter_s, unter, unter, f"Over-Under {s + 1}/{saetze_n}: unter"),
                        Seg(ueber_s, ueber, ueber, f"Over-Under {s + 1}/{saetze_n}: über")]
            if s < saetze_n - 1:
                out.append(Seg(M(5), 0.55, 0.55, "Erholung"))
        return out
    add("Schwelle", "Over-Under 3 × 9 min", "3 Sätze à 3 × (2 min 95 % / 1 min 105 %), 5 min Pause.",
        einfahren_hart(12) + over_under(3, 3, 0.95, 1.05, 120, 60) + ausfahren(10))
    add("Schwelle", "Over-Under 3 × 12 min", "3 Sätze à 4 × (2 min 92 % / 1 min 110 %), 5 min Pause.",
        einfahren_hart(12) + over_under(3, 4, 0.92, 1.10, 120, 60) + ausfahren(10))
    add("Schwelle", "Over-Under 2 × 16 min", "2 Sätze à 8 × (1 min 95 % / 1 min 108 %), 6 min Pause.",
        einfahren_hart(12) + over_under(2, 8, 0.95, 1.08, 60, 60) + ausfahren(10))

    # ===== VO2max (106–125 %) =====
    for n, d, p, r in [(5, 3, 1.20, 3), (6, 3, 1.18, 3), (4, 4, 1.15, 4), (5, 4, 1.15, 4),
                       (4, 5, 1.12, 5), (5, 5, 1.10, 5), (3, 6, 1.08, 5)]:
        add("VO2max", f"VO2max {n} × {d} min", f"{n} × {d} min bei {pct(p)}, {r} min locker.",
            einfahren_hart(12) + intervalle(n, M(d), p, M(r), 0.50, "VO2max") + ausfahren(10))
    add("VO2max", "VO2max Pyramide 2-3-4-3-2", "Intervalle bei 118 %, Pause so lang wie das Intervall.",
        einfahren_hart(12) + sum([[Seg(M(d), 1.18, 1.18, f"VO2max {d} min"), Seg(M(d), 0.50, 0.50, "Erholung")]
                                  for d in (2, 3, 4, 3, 2)], [])[:-1] + ausfahren(10))
    add("VO2max", "30/30 (2 × 10)", "2 Sätze à 10 × (30 s 120 % / 30 s 50 %), 5 min Satzpause.",
        einfahren_hart(12) + saetze(2, 10, 30, 1.20, 30, 0.50, 5, "30/30") + ausfahren(10))
    add("VO2max", "30/30 (3 × 10)", "3 Sätze à 10 × (30 s 120 % / 30 s 50 %), 5 min Satzpause.",
        einfahren_hart(12) + saetze(3, 10, 30, 1.20, 30, 0.50, 5, "30/30") + ausfahren(10))
    add("VO2max", "30/15 Rønnestad (3 × 13)", "3 Sätze à 13 × (30 s 120 % / 15 s 50 %), 3 min Satzpause.",
        einfahren_hart(12) + saetze(3, 13, 30, 1.20, 15, 0.50, 3, "30/15") + ausfahren(10))
    add("VO2max", "40/20 (2 × 10)", "2 Sätze à 10 × (40 s 125 % / 20 s 50 %), 5 min Satzpause.",
        einfahren_hart(12) + saetze(2, 10, 40, 1.25, 20, 0.50, 5, "40/20") + ausfahren(10))
    add("VO2max", "40/20 (3 × 8)", "3 Sätze à 8 × (40 s 125 % / 20 s 50 %), 5 min Satzpause.",
        einfahren_hart(12) + saetze(3, 8, 40, 1.25, 20, 0.50, 5, "40/20") + ausfahren(10))
    return W


# --- Zwift-Workouts (.zwo) ----------------------------------------------------
def lade_zwo(pfad: Path) -> Workout:
    root = ET.parse(pfad).getroot()
    name = (root.findtext("name") or pfad.stem).strip()
    beschr = (root.findtext("description") or "").strip()
    segs = []
    for el in root.find("workout"):
        a = el.attrib
        f = lambda k, d=0.0: float(a.get(k, d))
        tag = el.tag
        if tag == "SteadyState":
            p = f("Power", f("PowerLow", 0.5))
            segs.append(Seg(int(f("Duration")), p, p, "Konstant"))
        elif tag in ("Warmup", "Cooldown", "Ramp"):
            nm = {"Warmup": "Einfahren", "Cooldown": "Ausfahren", "Ramp": "Rampe"}[tag]
            segs.append(Seg(int(f("Duration")), f("PowerLow"), f("PowerHigh"), nm))
        elif tag == "IntervalsT":
            n = int(f("Repeat", 1))
            for i in range(n):
                segs.append(Seg(int(f("OnDuration")), f("OnPower"), f("OnPower"), f"Intervall {i + 1}/{n}"))
                segs.append(Seg(int(f("OffDuration")), f("OffPower"), f("OffPower"), "Erholung"))
        elif tag == "FreeRide":
            segs.append(Seg(int(f("Duration")), 0.6, 0.6, "Frei fahren", frei=True))
    return Workout(name, beschr, segs)


def lade_mrc_erg(pfad: Path) -> Workout:
    """MRC (Minuten, % FTP) bzw. ERG (Minuten, Watt; braucht 'FTP =' im Kopf) – Format von ErgDB/GoldenCheetah."""
    kopf, punkte, in_daten = {}, [], False
    for zeile in pfad.read_text(errors="replace").splitlines():
        z = zeile.strip()
        if z.upper().startswith("[COURSE DATA]"):
            in_daten = True; continue
        if z.upper().startswith("[END COURSE DATA]"):
            in_daten = False; continue
        if in_daten:
            teile = z.replace(",", " ").split()
            if len(teile) >= 2:
                try:
                    punkte.append((float(teile[0]), float(teile[1])))
                except ValueError:
                    pass
        elif "=" in z:
            k, v = z.split("=", 1)
            kopf[k.strip().upper()] = v.strip()
    if pfad.suffix.lower() == ".mrc":
        faktor = 1 / 100
    else:
        if "FTP" not in kopf:
            raise ValueError("ERG-Datei ohne 'FTP =' – Watt lassen sich nicht in % FTP umrechnen")
        faktor = 1 / float(kopf["FTP"])
    segs = []
    for (t0, p0), (t1, p1) in zip(punkte, punkte[1:]):
        d = int(round((t1 - t0) * 60))
        if d > 0:
            a, b = p0 * faktor, p1 * faktor
            nm = pct(a) if abs(a - b) < 1e-6 else f"{pct(a)} → {pct(b)}"
            segs.append(Seg(d, a, b, nm))
    name = kopf.get("DESCRIPTION") or kopf.get("FILE NAME") or pfad.stem
    return Workout(pfad.stem.replace("_", " "), name, segs)


def alle_workouts(ordner: Path):
    W = bibliothek()
    if ordner.is_dir():
        for p in sorted(q for q in ordner.rglob("*") if q.suffix.lower() in (".zwo", ".mrc", ".erg")):
            try:
                w = lade_zwo(p) if p.suffix.lower() == ".zwo" else lade_mrc_erg(p)
                rel = p.parent.relative_to(ordner)
                kat = rel.parts[0] if rel.parts else "Eigene"
                # Unterordner-Namen tolerant auf Kategorien abbilden
                treffer = [k for k in KATEGORIEN if k.lower().replace(" ", "") == kat.lower().replace(" ", "")]
                w.kategorie = treffer[0] if treffer else kat
                W.append(w)
            except Exception as e:
                print(f"Kann {p} nicht lesen: {e}")
    return W
