"""Trainingsbelastung: NP, IF, TSS sowie CTL/ATL/TSB (Performance Management)."""
import json
import math
from datetime import date, timedelta
from pathlib import Path

VERLAUF = Path(__file__).resolve().parent / "verlauf.json"


def np_if_tss(watts, ftp):
    """watts: Liste von 1-s-Werten. Gibt (NP, IF, TSS) zurück."""
    n = len(watts)
    if n < 30 or ftp <= 0:
        return None, None, None
    roll, s = [], sum(watts[:30])
    roll.append(s / 30)
    for i in range(30, n):
        s += watts[i] - watts[i - 30]
        roll.append(s / 30)
    np_ = (sum(r ** 4 for r in roll) / len(roll)) ** 0.25
    if_ = np_ / ftp
    tss = n * np_ * if_ / (ftp * 3600) * 100
    return round(np_), round(if_, 2), round(tss)


def lade():
    try:
        return json.loads(VERLAUF.read_text())
    except Exception:
        return []


def eintragen(eintrag: dict):
    v = lade()
    v.append(eintrag)
    VERLAUF.write_text(json.dumps(v, indent=1, ensure_ascii=False))


def pmc(bis: date | None = None, verlauf=None):
    """CTL (42 Tage), ATL (7 Tage), TSB = CTL − ATL von gestern. Gibt dict für 'bis' zurück."""
    verlauf = lade() if verlauf is None else verlauf
    bis = bis or date.today()
    if not verlauf:
        return {"ctl": 0.0, "atl": 0.0, "tsb": 0.0}
    tage = {}
    for e in verlauf:
        d = date.fromisoformat(e["datum"][:10])
        tage[d] = tage.get(d, 0) + (e.get("tss") or 0)
    d = min(tage)
    ctl = atl = 0.0
    k_ctl, k_atl = 1 - math.exp(-1 / 42), 1 - math.exp(-1 / 7)
    tsb = 0.0
    while d <= bis:
        tsb = ctl - atl  # Form = Stand vom Vortag
        t = tage.get(d, 0)
        ctl += (t - ctl) * k_ctl
        atl += (t - atl) * k_atl
        d += timedelta(days=1)
    return {"ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(tsb, 1)}
