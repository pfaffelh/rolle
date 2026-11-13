#!/usr/bin/env python3
"""ERG-Training nach FTP für FTMS-Rollen (z. B. Wahoo KICKR)."""
import json
import os
import socket
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from tkinter import ttk

import metriken

from ftms import Trainer
from workouts import KATEGORIEN, alle_workouts

HIER = Path(__file__).resolve().parent
EINST = HIER / "einstellungen.json"
FAHRTEN = HIER / "fahrten"


def zone_farbe(anteil):
    for grenze, farbe in [(0.55, "#9e9e9e"), (0.75, "#3d8bfd"), (0.90, "#2fb344"),
                          (1.05, "#f2c94c"), (1.20, "#f2994a"), (9, "#e5484d")]:
        if anteil < grenze:
            return farbe


def mmss(s):
    s = max(0, int(round(s)))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def beste_mittel(werte, n):
    if len(werte) < n:
        return None
    summe = sum(werte[:n]); best = summe
    for i in range(n, len(werte)):
        summe += werte[i] - werte[i - n]
        best = max(best, summe)
    return best / n


class App:
    def __init__(self, root):
        self.root = root
        root.title("ERG-Training")
        root.geometry("1000x700")
        self.cfg = {"ftp": 250, "rolle": None}
        try:
            self.cfg.update(json.loads(EINST.read_text()))
        except Exception:
            pass

        self.trainer = Trainer(self.data_cb, self.status_cb)
        self.devices = []
        self.workouts = alle_workouts(HIER / "workouts")

        # Messwerte
        self.letzte_daten = 0.0
        self.leistung = deque(maxlen=3)
        self.cadence = 0.0
        self.speed = 0.0

        # Workout-Zustand
        self.wo = None
        self.laeuft = False
        self.pause = False
        self.t = 0.0
        self.seg_idx = -1
        self.offset = 0
        self.manuell = 150
        self.gesendet = None          # ("erg", watt) oder ("frei",)
        self.gesendet_zeit = 0.0
        self.aufnahme = []
        self.letzter_tick = time.time()

        self._baue_gui()
        self.workout_gewaehlt()
        self.tick()
        if self.cfg.get("mini"):
            self.root.after(300, self.mini_an)

    # ------------------------------------------------------------------ GUI
    def _baue_gui(self):
        r = self.root
        style = ttk.Style()
        style.configure("Big.TLabel", font=("Helvetica", 40, "bold"))
        style.configure("Mid.TLabel", font=("Helvetica", 13))
        style.configure("Seg.TLabel", font=("Helvetica", 18, "bold"))

        top = ttk.Frame(r, padding=6); top.pack(fill="x")
        ttk.Button(top, text="Suchen", command=self.scan).pack(side="left")
        self.dev_combo = ttk.Combobox(top, state="readonly", width=26); self.dev_combo.pack(side="left", padx=4)
        ttk.Button(top, text="Verbinden", command=self.connect).pack(side="left")
        ttk.Label(top, text="   FTP:").pack(side="left")
        self.ftp_var = tk.IntVar(value=self.cfg["ftp"])
        sp = ttk.Spinbox(top, from_=50, to=600, increment=1, width=5, textvariable=self.ftp_var,
                         command=self.ftp_geaendert)
        sp.pack(side="left"); sp.bind("<Return>", lambda e: self.ftp_geaendert()); sp.bind("<FocusOut>", lambda e: self.ftp_geaendert())
        ttk.Label(top, text="W").pack(side="left")
        self.pmc_text = tk.StringVar()
        ttk.Label(top, textvariable=self.pmc_text, foreground="#333").pack(side="left", padx=12)
        self.pmc_anzeigen()
        self.status = tk.StringVar(value="Woosh/Handy trennen, dann 'Suchen' und 'Verbinden'.")
        ttk.Label(r, textvariable=self.status, foreground="#666").pack(fill="x", padx=8)

        anz = ttk.Frame(r, padding=4); anz.pack(fill="x")
        self.v = {}
        for i, (k, lab) in enumerate([("ist", "Watt (3 s)"), ("ziel", "Ziel Watt"), ("cad", "U/min"),
                                      ("seg", "Intervall-Rest"), ("rest", "Gesamt-Rest")]):
            f = ttk.Frame(anz); f.grid(row=0, column=i, sticky="ew"); anz.columnconfigure(i, weight=1)
            self.v[k] = tk.StringVar(value="–")
            ttk.Label(f, textvariable=self.v[k], style="Big.TLabel", anchor="center").pack(fill="x")
            ttk.Label(f, text=lab, style="Mid.TLabel", anchor="center").pack(fill="x")

        self.seg_text = tk.StringVar(); self.next_text = tk.StringVar()
        ttk.Label(r, textvariable=self.seg_text, style="Seg.TLabel", anchor="center").pack(fill="x", pady=(6, 0))
        ttk.Label(r, textvariable=self.next_text, style="Mid.TLabel", anchor="center", foreground="#666").pack(fill="x")

        self.canvas = tk.Canvas(r, height=220, bg="white", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=6)
        self.canvas.bind("<Configure>", lambda e: self.zeichne_profil())

        unten = ttk.Frame(r, padding=6); unten.pack(fill="x")
        wahl = ttk.Frame(r, padding=(6, 0)); wahl.pack(fill="x", before=unten)
        kats = [k for k in KATEGORIEN if any(w.kategorie == k for w in self.workouts)]
        kats += sorted({w.kategorie for w in self.workouts} - set(kats))
        ttk.Label(wahl, text="Kategorie:").pack(side="left")
        self.kat_combo = ttk.Combobox(wahl, state="readonly", width=14, values=kats)
        self.kat_combo.pack(side="left", padx=4)
        self.kat_combo.bind("<<ComboboxSelected>>", lambda e: self.kategorie_gewaehlt())
        ttk.Label(wahl, text="  Workout:").pack(side="left")
        self.wo_combo = ttk.Combobox(wahl, state="readonly", width=60)
        self.wo_combo.pack(side="left", padx=4, fill="x", expand=True)
        self.wo_combo.bind("<<ComboboxSelected>>", lambda e: self.workout_gewaehlt())
        letzte = "Standard" if "Standard" in kats else self.cfg.get("kategorie")
        self.kat_combo.current(kats.index(letzte) if letzte in kats else (kats.index("Ausdauer") if "Ausdauer" in kats else 0))
        self.kategorie_gewaehlt(erste=True)
        self.start_text = tk.StringVar(value="▶ Start")
        self.start_btn = ttk.Button(unten, textvariable=self.start_text, command=self.start_pause); self.start_btn.pack(side="left", padx=2)
        ttk.Button(unten, text="⏭ Überspringen", command=self.ueberspringen).pack(side="left", padx=2)
        ttk.Button(unten, text="⏹ Beenden", command=self.beenden).pack(side="left", padx=2)
        ttk.Button(unten, text="▣ Mini", command=self.mini_an).pack(side="right", padx=2)
        ttk.Label(unten, text="   Intensität:").pack(side="left")
        ttk.Button(unten, text="−", width=3, command=lambda: self.intensitaet(-1)).pack(side="left")
        self.off_text = tk.StringVar(value="100 %")
        ttk.Label(unten, textvariable=self.off_text, width=6, anchor="center").pack(side="left")
        ttk.Button(unten, text="+", width=3, command=lambda: self.intensitaet(1)).pack(side="left")

        self.beschr = tk.StringVar()
        ttk.Label(r, textvariable=self.beschr, foreground="#444", wraplength=960).pack(fill="x", padx=8)
        ttk.Label(r, text="Tasten: Leertaste = Start/Pause · ↑/↓ = Intensität ±1 % (ohne Workout: ±5 W) · "
                          "Workouts als .zwo in den Ordner 'workouts' legen",
                  foreground="#888").pack(fill="x", padx=8, pady=(0, 4))

        self._tasten(r)
        r.bind("<m>", lambda e: self.mini_an())
        r.protocol("WM_DELETE_WINDOW", self.quit)

    def _tasten(self, w):
        w.bind("<space>", lambda e: self.start_pause())
        w.bind("<Up>", lambda e: self.intensitaet(1)); w.bind("<Down>", lambda e: self.intensitaet(-1))

    # ------------------------------------------------------------ Mini-Fenster
    def mini_an(self):
        if getattr(self, "mini", None):
            self.mini.lift(); return
        m = tk.Toplevel(self.root)
        self.mini = m
        m.title("Rolle")
        m.geometry(self.cfg.get("mini_geo", "430x205"))
        m.minsize(300, 150)
        m.attributes("-topmost", True)
        # -alpha wirkt unter X11 nur, wenn das Fenster schon angezeigt wird –
        # daher bei jedem Anzeigen (Map) setzen, zur Sicherheit nochmals verzögert
        m.bind("<Map>", lambda e: e.widget is m and self._setze_alpha(self.cfg.get("mini_alpha", 0.7)))
        m.after(1000, lambda: self._setze_alpha(self.cfg.get("mini_alpha", 0.7)))
        m.configure(bg="white")
        st = ttk.Style()
        st.configure("MiniBig.TLabel", font=("Helvetica", 30, "bold"), background="white")
        st.configure("MiniKl.TLabel", font=("Helvetica", 9), foreground="#777", background="white")
        st.configure("MiniSeg.TLabel", font=("Helvetica", 11, "bold"), background="white")
        st.configure("Mini.TFrame", background="white")

        zahlen = ttk.Frame(m, style="Mini.TFrame"); zahlen.pack(fill="x", padx=4, pady=(2, 0))
        for i, (k, lab) in enumerate([("ziel", "Ziel W"), ("ist", "Ist W"), ("cad", "U/min"), ("seg", "Rest")]):
            f = ttk.Frame(zahlen, style="Mini.TFrame"); f.grid(row=0, column=i, sticky="ew")
            zahlen.columnconfigure(i, weight=1)
            ttk.Label(f, textvariable=self.v[k], style="MiniBig.TLabel", anchor="center").pack(fill="x")
            ttk.Label(f, text=lab, style="MiniKl.TLabel", anchor="center").pack(fill="x")
        ttk.Label(m, textvariable=self.seg_text, style="MiniSeg.TLabel", anchor="center").pack(fill="x")

        self.mini_canvas = tk.Canvas(m, height=40, bg="white", highlightthickness=0)
        self.mini_canvas.pack(fill="both", expand=True, padx=4)
        self.mini_canvas.bind("<Configure>", lambda e: self._zeichne_profil(self.mini_canvas))

        leiste = ttk.Frame(m, style="Mini.TFrame"); leiste.pack(fill="x", padx=4, pady=2)
        self.mini_start = ttk.Button(leiste, width=9, textvariable=self.start_text, command=self.start_pause)
        self.mini_start.pack(side="left")
        ttk.Button(leiste, text="⏭", width=3, command=self.ueberspringen).pack(side="left")
        ttk.Button(leiste, text="−", width=2, command=lambda: self.intensitaet(-1)).pack(side="left", padx=(8, 0))
        ttk.Label(leiste, textvariable=self.off_text, width=6, anchor="center", style="MiniKl.TLabel").pack(side="left")
        ttk.Button(leiste, text="+", width=2, command=lambda: self.intensitaet(1)).pack(side="left")
        ttk.Label(leiste, textvariable=self.v["rest"], style="MiniKl.TLabel").pack(side="left", padx=8)
        ttk.Button(leiste, text="⤢", width=3, command=self.mini_aus).pack(side="right")

        self._tasten(m)
        m.bind("<m>", lambda e: self.mini_aus())
        # Mausrad über dem Mini-Fenster: Durchsichtigkeit einstellen
        m.bind("<Button-4>", lambda e: self._setze_alpha(self.cfg.get("mini_alpha", 0.7) + 0.05, True))
        m.bind("<Button-5>", lambda e: self._setze_alpha(self.cfg.get("mini_alpha", 0.7) - 0.05, True))
        m.bind("<MouseWheel>", lambda e: self._setze_alpha(
            self.cfg.get("mini_alpha", 0.7) + (0.05 if e.delta > 0 else -0.05), True))
        m.protocol("WM_DELETE_WINDOW", self.mini_aus)
        self.root.iconify()
        self.cfg["mini"] = True; self.speichere_cfg()

    def _setze_alpha(self, a, speichern=False):
        a = round(min(1.0, max(0.3, a)), 2)
        self.cfg["mini_alpha"] = a
        try:
            self.mini.attributes("-alpha", a)
        except Exception:
            pass
        if speichern:
            self.speichere_cfg()

    def mini_aus(self):
        if not getattr(self, "mini", None):
            return
        self.cfg["mini_geo"] = self.mini.geometry()
        self.cfg["mini"] = False; self.speichere_cfg()
        self.mini.destroy(); self.mini = None
        self.root.deiconify(); self.root.lift()

    # ------------------------------------------------------------ Meldungen
    def dialog(self, titel, text, frage=False, kopf=None, farbe="#222"):
        """Meldungsfenster, das immer im Vordergrund liegt – auch über dem Mini-Fenster.
        Mit frage=True gibt es Ja/Nein und liefert True bei Ja."""
        eltern = self.mini if getattr(self, "mini", None) else self.root
        d = tk.Toplevel(self.root)
        d.title(titel)
        d.resizable(False, False)
        if eltern.winfo_viewable():
            d.transient(eltern)
        d.attributes("-topmost", True)
        rahmen = ttk.Frame(d, padding=16); rahmen.pack(fill="both", expand=True)
        if kopf:
            ttk.Label(rahmen, text=kopf, font=("Helvetica", 16, "bold"), foreground=farbe).pack(anchor="w", pady=(0, 8))
        ttk.Label(rahmen, text=text, justify="left", font=("Helvetica", 11)).pack(anchor="w")
        antwort = {"ja": False}

        def schliesse(ja):
            antwort["ja"] = ja
            d.destroy()
        knoepfe = ttk.Frame(rahmen); knoepfe.pack(anchor="e", pady=(14, 0))
        if frage:
            ttk.Button(knoepfe, text="Nein", command=lambda: schliesse(False)).pack(side="right", padx=(6, 0))
            ja = ttk.Button(knoepfe, text="Ja", command=lambda: schliesse(True)); ja.pack(side="right")
        else:
            ja = ttk.Button(knoepfe, text="OK", command=lambda: schliesse(True)); ja.pack(side="right")
        d.bind("<Return>", lambda e: schliesse(True))
        d.bind("<Escape>", lambda e: schliesse(False))
        d.protocol("WM_DELETE_WINDOW", lambda: schliesse(False))
        d.update_idletasks()
        x = (d.winfo_screenwidth() - d.winfo_reqwidth()) // 2
        y = (d.winfo_screenheight() - d.winfo_reqheight()) // 3
        d.geometry(f"+{x}+{y}")
        d.deiconify(); d.lift(); d.focus_force(); ja.focus_set()
        try:
            d.grab_set()
        except tk.TclError:
            pass
        self.root.bell()
        d.wait_window()
        return antwort["ja"]

    # ------------------------------------------------------------ Einstellungen
    def speichere_cfg(self):
        try:
            EINST.write_text(json.dumps(self.cfg, indent=1))
        except Exception:
            pass

    def ftp_geaendert(self):
        try:
            ftp = int(self.ftp_var.get())
        except Exception:
            return
        if 50 <= ftp <= 600 and ftp != self.cfg["ftp"]:
            self.cfg["ftp"] = ftp
            self.speichere_cfg()
            self.wo = self.wo_basis.als_ftp(ftp)
            if not self.laeuft:
                self.kategorie_gewaehlt(erste=True)
            self.zeichne_profil()

    def pmc_anzeigen(self):
        p = metriken.pmc()
        self.pmc_text.set(f"Fitness (CTL) {p['ctl']:.0f} · Ermüdung (ATL) {p['atl']:.0f} · Form (TSB) {p['tsb']:+.0f}")

    @property
    def ftp(self):
        return self.cfg["ftp"]

    # ------------------------------------------------------------ Workout
    def kategorie_gewaehlt(self, erste=False):
        kat = self.kat_combo.get()
        self.liste = [w for w in self.workouts if w.kategorie == kat]
        werte = []
        for w in self.liste:
            if_, tss = w.als_ftp(self.ftp).plan_if_tss()
            werte.append(f"{w.name}  ·  {mmss(w.dauer)}  ·  TSS ~{tss}  ·  IF {if_:.2f}")
        self.wo_combo["values"] = werte
        idx = 0
        if self.cfg.get("workout") in [w.name for w in self.liste]:
            idx = [w.name for w in self.liste].index(self.cfg["workout"])
        self.wo_combo.current(idx)
        if not erste:
            self.cfg["kategorie"] = kat; self.speichere_cfg()
            self.workout_gewaehlt()

    def workout_gewaehlt(self):
        if self.laeuft:
            return
        self.ende_meldung = None
        self.wo_basis = self.liste[self.wo_combo.current()]
        self.wo = self.wo_basis.als_ftp(self.ftp)
        self.cfg["workout"] = self.wo.name; self.speichere_cfg()
        self.beschr.set(self.wo.beschreibung)
        self.t = 0; self.seg_idx = -1
        self.zeichne_profil()
        self.anzeige_workout()

    def segment_bei(self, t):
        a = 0
        for i, s in enumerate(self.wo.segmente):
            if t < a + s.dauer:
                return i, t - a
            a += s.dauer
        return None, 0

    def start_pause(self):
        if not self.laeuft:
            if not (self.trainer.client and self.trainer.client.is_connected):
                if not self.dialog("Nicht verbunden", "Die Rolle ist nicht verbunden. Trotzdem starten?", frage=True):
                    return
            self.laeuft = True; self.pause = False; self.ende_meldung = None
            self.t = 0; self.seg_idx = -1; self.aufnahme = []; self.offset = 0
            self.off_text.set("100 %")
            self.startzeit = datetime.now(timezone.utc)
            self.wo_combo.configure(state="disabled"); self.kat_combo.configure(state="disabled")
            self.start_text.set("⏸ Pause")
            self.status_cb("Workout läuft – die Zeit zählt, sobald du trittst.")
        else:
            self.pause = not self.pause
            self.start_text.set("▶ Weiter" if self.pause else "⏸ Pause")

    def ueberspringen(self):
        if not self.laeuft:
            return
        i, im = self.segment_bei(self.t)
        if i is not None:
            self.t += self.wo.segmente[i].dauer - im

    def intensitaet(self, d):
        if self.laeuft:
            self.offset = max(-50, min(50, self.offset + d))
            self.off_text.set(f"{100 + self.offset} %")
        else:
            self.manuell = max(0, self.manuell + 5 * d)
        self.gesendet = None  # sofort neu senden

    def beenden(self):
        if not self.laeuft:
            return
        if self.t < self.wo.dauer and not self.dialog("Beenden", "Workout beenden und speichern?", frage=True):
            return
        self.fertig()

    def fertig(self):
        self.laeuft = False
        self.wo_combo.configure(state="readonly"); self.kat_combo.configure(state="readonly")
        self.start_text.set("▶ Start")
        self.manuell = int(self.ftp * 0.45)
        self.gesendet = None
        watts = [s["p"] for s in self.aufnahme]
        fehler = None
        try:
            pfad = self.speichere_tcx()
            if pfad and (not pfad.exists() or pfad.stat().st_size == 0):
                raise OSError(f"Datei {pfad} fehlt oder ist leer")
        except Exception as e:
            pfad, fehler = None, f"Fahrt konnte nicht gespeichert werden:\n{e}"
        if pfad:
            text = f"Datei: {pfad}"
        else:
            text = fehler or "Zu wenig Daten aufgezeichnet – nichts gespeichert."
        if watts:
            text += f"\nDauer {mmss(len(watts))}, Ø {sum(watts) / len(watts):.0f} W"
            np_, if_, tss = metriken.np_if_tss(watts, self.ftp)
            if pfad and tss is not None:
                try:
                    metriken.eintragen({"datum": self.aufnahme[0]["zeit"].astimezone().isoformat(timespec="seconds"),
                                        "name": self.wo.name, "dauer_s": len(watts), "ftp": self.ftp,
                                        "np": np_, "if": if_, "tss": tss,
                                        "avg_w": round(sum(watts) / len(watts)), "datei": pfad.name})
                    p = metriken.pmc()
                    self.pmc_anzeigen()
                    text += (f"\nNP {np_} W · IF {if_:.2f} · TSS {tss}"
                             f"\nCTL {p['ctl']:.0f} · ATL {p['atl']:.0f} · TSB {p['tsb']:+.0f}"
                             f"\n\nIm Verlauf eingetragen.")
                except Exception as e:
                    fehler = f"Eintrag in verlauf.json fehlgeschlagen: {e}"
                    text += "\n\n⚠ " + fehler
        neu = None
        if self.wo.test == "rampe":
            b = beste_mittel(watts, 60)
            if b:
                neu = round(0.75 * b)
                text += f"\n\nBeste 1-min-Leistung: {b:.0f} W\nGeschätzte FTP (75 %): {neu} W"
        elif self.wo.test == "8min":
            b = beste_mittel(watts, 480)
            if b:
                neu = round(0.90 * b)
                text += f"\n\nBeste 8-min-Leistung: {b:.0f} W\nGeschätzte FTP (90 %): {neu} W"
        elif self.wo.test == "20min":
            b = beste_mittel(watts, 1200)
            if b:
                neu = round(0.95 * b)
                text += f"\n\nBeste 20-min-Leistung: {b:.0f} W\nGeschätzte FTP (95 %): {neu} W"
        if pfad and not fehler:
            kopf, farbe = "✓ Fahrt gespeichert", "#2fb344"
        else:
            kopf, farbe = "⚠ Nicht (vollständig) gespeichert", "#d63939"
        self.ende_meldung = f"{kopf} · {datetime.now():%H:%M}" + (f" · {pfad.name}" if pfad else "")
        self.seg_text.set(self.ende_meldung)
        if neu:
            if self.dialog("Test-Ergebnis", text + f"\n\nNeue FTP {neu} W übernehmen (bisher {self.ftp} W)?",
                           frage=True, kopf=kopf, farbe=farbe):
                self.ftp_var.set(neu); self.ftp_geaendert()
        else:
            self.dialog("Workout beendet", text, kopf=kopf, farbe=farbe)
        self.status_cb("Workout beendet. " + (f"Datei: {pfad}" if pfad else ""))

    # ------------------------------------------------------------ Takt (jede Sekunde)
    def tick(self):
        jetzt = time.time()
        dt = min(2.0, jetzt - self.letzter_tick)
        self.letzter_tick = jetzt
        frisch = jetzt - self.letzte_daten < 3
        p = round(sum(self.leistung) / len(self.leistung)) if (self.leistung and frisch) else None
        self.v["ist"].set("–" if p is None else str(p))
        self.v["cad"].set(f"{self.cadence:.0f}" if frisch else "–")

        if self.laeuft:
            aktiv = frisch and (self.cadence > 0 or (p or 0) > 0) and not self.pause
            if aktiv:
                self.t += dt
                self.aufnahme.append({"zeit": datetime.now(timezone.utc), "p": self.leistung[-1] if self.leistung else 0,
                                      "cad": self.cadence, "v": self.speed})
            if self.t >= self.wo.dauer:
                self.fertig()
            else:
                if not aktiv and not self.pause:
                    self.status_cb("Pausiert – treten zum Fortsetzen" if self.t > 0 else
                                   "Bereit – fang an zu treten, dann läuft die Zeit.")
                elif self.pause:
                    self.status_cb("Pause (Leertaste zum Fortsetzen)")
                else:
                    self.status_cb("Workout läuft")
                self.steuere()
        else:
            self.sende(("erg", self.manuell))
            self.v["ziel"].set(str(self.manuell))

        self.anzeige_workout()
        self.zeichne_live()
        self.root.after(1000 - int((time.time() * 1000) % 1000) or 1000, self.tick)

    def steuere(self):
        i, im = self.segment_bei(self.t)
        if i is None:
            return
        seg = self.wo.segmente[i]
        if i != self.seg_idx:
            if self.seg_idx >= 0:
                self.root.bell()
            self.seg_idx = i
        rest = seg.dauer - im
        if 0 < rest <= 3.5 and int(rest) != getattr(self, "_letzter_piep", -1):
            self._letzter_piep = int(rest); self.root.bell()
        if seg.frei:
            self.sende(("frei",))
            self.v["ziel"].set("frei")
        else:
            w = round(self.ftp * seg.anteil(im) * (1 + self.offset / 100))
            self.sende(("erg", w))
            self.v["ziel"].set(str(w))

    def sende(self, befehl):
        jetzt = time.time()
        if befehl == self.gesendet and jetzt - self.gesendet_zeit < 15:
            return
        if not (self.trainer.client and self.trainer.client.is_connected):
            return
        self.gesendet, self.gesendet_zeit = befehl, jetzt
        if befehl[0] == "erg":
            self.trainer.run(self.trainer.set_power(befehl[1]))
        else:
            self.trainer.run(self.trainer.set_grade(0.0))

    # ------------------------------------------------------------ Anzeige
    def anzeige_workout(self):
        if not self.wo:
            return
        i, im = self.segment_bei(self.t)
        if not self.laeuft:
            if getattr(self, "ende_meldung", None):
                self.seg_text.set(self.ende_meldung)
            else:
                self.seg_text.set(f"{self.wo.name} – {mmss(self.wo.dauer)}"
                                  f"   (ohne Workout: ERG {self.manuell} W, ↑/↓ ändert)")
            self.next_text.set("")
            self.v["seg"].set("–"); self.v["rest"].set(mmss(self.wo.dauer))
            return
        if i is None:
            return
        seg = self.wo.segmente[i]
        if seg.frei:
            ziel = "frei fahren"
        elif getattr(self.wo, "feste_watt", False):
            a, b = round(seg.start * self.ftp), round(seg.ende * self.ftp)
            ziel = f"{a} W" if a == b else f"{a} → {b} W"
        else:
            ziel = (f"{seg.start * 100:.0f} % FTP" if seg.start == seg.ende
                    else f"{seg.start * 100:.0f} → {seg.ende * 100:.0f} % FTP")
        self.seg_text.set(f"{seg.name}  ·  {ziel}")
        if i + 1 < len(self.wo.segmente):
            n = self.wo.segmente[i + 1]
            nz = "frei" if n.frei else f"{round(self.ftp * n.start * (1 + self.offset / 100))} W"
            self.next_text.set(f"Danach: {n.name} – {mmss(n.dauer)} @ {nz}")
        else:
            self.next_text.set("Danach: fertig!")
        self.v["seg"].set(mmss(seg.dauer - im))
        self.v["rest"].set(mmss(self.wo.dauer - self.t))

    def _geo(self, c=None):
        c = c or self.canvas
        w, h = max(c.winfo_width(), 100), max(c.winfo_height(), 60)
        maxa = max([max(s.start, s.ende) for s in self.wo.segmente] + [1.2]) * 1.1
        return w, h, maxa

    def zeichne_profil(self):
        for c in self.leinwaende():
            self._zeichne_profil(c)

    def leinwaende(self):
        cs = [self.canvas]
        if getattr(self, "mini", None):
            cs.append(self.mini_canvas)
        return cs

    def _zeichne_profil(self, c):
        if not self.wo:
            return
        c.delete("all")
        w, h, maxa = self._geo(c)
        D = self.wo.dauer or 1
        x = lambda t: t / D * w
        y = lambda a: h - a / maxa * (h - 14)
        t0 = 0
        for s in self.wo.segmente:
            farbe = "#cfd8dc" if s.frei else zone_farbe((s.start + s.ende) / 2)
            c.create_polygon(x(t0), h, x(t0), y(s.start), x(t0 + s.dauer), y(s.ende), x(t0 + s.dauer), h,
                             fill=farbe, outline="")
            t0 += s.dauer
        c.create_line(0, y(1.0), w, y(1.0), fill="#555", dash=(4, 3))
        if c is self.canvas:
            c.create_text(4, y(1.0) - 8, text=f"FTP {self.ftp} W", anchor="w", fill="#555")
        self._zeichne_live(c)

    def zeichne_live(self):
        for c in self.leinwaende():
            self._zeichne_live(c)

    def _zeichne_live(self, c):
        if not self.wo:
            return
        c.delete("live")
        w, h, maxa = self._geo(c)
        D = self.wo.dauer or 1
        if self.aufnahme:
            # Ist-Leistung als Linie (auf Pixelbreite verdichtet)
            n = len(self.aufnahme)
            schritt = max(1, int(n / max(1, w * self.t / D)))
            pts = []
            for k in range(0, n, schritt):
                block = self.aufnahme[k:k + schritt]
                p = sum(b["p"] for b in block) / len(block)
                pts += [(k + schritt / 2) / n * self.t / D * w, h - (p / self.ftp) / maxa * (h - 14)]
            if len(pts) >= 4:
                c.create_line(*pts, fill="#222", width=1.5, tags="live")
        xp = self.t / D * w
        c.create_line(xp, 0, xp, h, fill="#000", width=2, tags="live")

    # ------------------------------------------------------------ Speichern
    def speichere_tcx(self):
        if len(self.aufnahme) < 10:
            return None
        FAHRTEN.mkdir(exist_ok=True)
        start = self.aufnahme[0]["zeit"]
        name = "".join(ch if ch.isalnum() else "_" for ch in self.wo.name)[:40]
        pfad = FAHRTEN / f"{start.astimezone():%Y-%m-%d_%H%M}_{name}.tcx"
        iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
        dist = 0.0
        pts = []
        for s in self.aufnahme:
            dist += s["v"] / 3.6
            pts.append(f"""<Trackpoint><Time>{iso(s['zeit'])}</Time><DistanceMeters>{dist:.1f}</DistanceMeters>"""
                       f"""<Cadence>{int(s['cad'])}</Cadence><Extensions><ns3:TPX><ns3:Speed>{s['v'] / 3.6:.2f}</ns3:Speed>"""
                       f"""<ns3:Watts>{int(s['p'])}</ns3:Watts></ns3:TPX></Extensions></Trackpoint>""")
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
 xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">
<Activities><Activity Sport="Biking"><Id>{iso(start)}</Id>
<Lap StartTime="{iso(start)}"><TotalTimeSeconds>{len(self.aufnahme)}</TotalTimeSeconds>
<DistanceMeters>{dist:.1f}</DistanceMeters><Calories>{int(sum(s['p'] for s in self.aufnahme) / 1000)}</Calories>
<Intensity>Active</Intensity><TriggerMethod>Manual</TriggerMethod>
<Track>
{chr(10).join(pts)}
</Track></Lap>
<Notes>{self.wo.name} (FTP {self.ftp} W)</Notes>
</Activity></Activities></TrainingCenterDatabase>
"""
        pfad.write_text(xml)
        return pfad

    # ------------------------------------------------------------ Verbindung
    def scan(self):
        fut = self.trainer.run(self.trainer.scan())

        def done(f):
            try:
                self.devices = f.result()
            except Exception as e:
                self.status_cb(f"Fehler beim Suchen: {e!r}"); return
            self.root.after(0, self._fuelle_geraete)
        fut.add_done_callback(done)

    def _fuelle_geraete(self):
        self.dev_combo["values"] = [f"{n} ({a})" for a, n in self.devices]
        if self.devices:
            idx = next((i for i, (a, _) in enumerate(self.devices) if a == self.cfg.get("rolle")), 0)
            self.dev_combo.current(idx)
            if len(self.devices) == 1:
                self.connect()

    def connect(self):
        i = self.dev_combo.current()
        if i < 0:
            self.status_cb("Erst 'Suchen' und eine Rolle auswählen."); return
        adr = self.devices[i][0]
        fut = self.trainer.run(self.trainer.connect(adr))

        def done(f):
            try:
                f.result()
                self.cfg["rolle"] = adr; self.speichere_cfg()
                self.gesendet = None
            except Exception as e:
                self.status_cb(f"Verbindung fehlgeschlagen: {e!r}")
        fut.add_done_callback(done)

    def quit(self):
        if getattr(self, "mini", None):
            self.cfg["mini_geo"] = self.mini.geometry(); self.speichere_cfg()
        if self.laeuft and self.aufnahme:
            if self.dialog("Beenden", "Workout läuft. Vorher speichern?", frage=True):
                self.speichere_tcx()
        try:
            self.trainer.run(self.trainer.disconnect()).result(timeout=3)
        except Exception:
            pass
        self.root.destroy()

    # ------------------------------------------------------------ BLE-Callbacks
    def status_cb(self, text):
        self.root.after(0, lambda: self.status.set(text))

    def data_cb(self, d):
        def upd():
            self.letzte_daten = time.time()
            if "power" in d:
                self.leistung.append(d["power"])
            if "cadence" in d:
                self.cadence = d["cadence"]
            if "speed" in d:
                self.speed = d["speed"]
        self.root.after(0, upd)


# ------------------------------------------------------------ nur ein Fenster
SPERRE = "\0ergtraining-" + str(os.getuid())  # abstrakter Unix-Socket, verschwindet mit dem Prozess


def einzige_instanz():
    """Gibt einen lauschenden Socket zurück – oder None, wenn das Programm schon läuft
    (dann wurde das laufende Fenster bereits nach vorne geholt)."""
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(SPERRE)
    except OSError:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
                c.settimeout(2)
                c.connect(SPERRE)
                c.sendall(b"zeigen")
        except OSError:
            pass
        return None
    srv.listen(2)
    return srv


def nach_vorne(app):
    w = app.mini if getattr(app, "mini", None) else app.root
    w.deiconify()
    w.lift()
    w.attributes("-topmost", True)
    if w is app.root:
        w.after(300, lambda: w.attributes("-topmost", False))
    w.focus_force()


def lausche(srv, app):
    while True:
        try:
            conn, _ = srv.accept()
            with conn:
                conn.recv(16)
            app.root.after(0, lambda: nach_vorne(app))
        except OSError:
            return


if __name__ == "__main__":
    srv = einzige_instanz()
    if srv is None:
        print("ERG-Training läuft bereits – Fenster wurde nach vorne geholt.")
        raise SystemExit(0)
    root = tk.Tk(className="ergtraining")
    try:
        root.iconphoto(True, tk.PhotoImage(file=str(HIER / "icon.png")))
    except Exception:
        pass
    app = App(root)
    threading.Thread(target=lausche, args=(srv, app), daemon=True).start()
    root.mainloop()
