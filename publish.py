#!/usr/bin/env python3
"""
Erzeugt data/current.json mit aktuellen Messwerten für das Live-Widget
auf schutzblech-bonn.de/analyse.html

Quellen:
  ÖPNV: VRR EFA API (aktuelle Abfahrten, Verspätungsberechnung)
  MIV:  bundesstaustadt.de API (Amt 66 Bonn, öffentlich)
  7-Tage-Schnitt: aus gesammelten CSV-Daten (delays_*.csv)

Wird nach collect.py ausgeführt (GitHub Actions).
"""

import csv
import json
import os
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
OUT_FILE = DATA_DIR / "current.json"

# MIV-Routen auf bundesstaustadt.de die wir beobachten
MIV_ROUTE_IDS = {
    12:  "A59 → Kennedybrücke",   # Hauptzufahrt Beuel→Stadt, am stärksten betroffen
    149: "Kennedybrücke → A59",   # Gegenrichtung
    14:  "Kölnstr. → Bertha",     # Innenstadtzufahrt
}
MIV_PRIMARY = 12  # Hauptindikator für das Widget


# ── ÖPNV: aktuelle Abfahrten abrufen ─────────────────────────────────────────
STOPS_BY_CORRIDOR = {
    "stadtbahn": [
        "de:05314:61101",   # Bonn Hbf Stadtbahn (U-Bahnsteig)
        "de:05314:61110",   # Universität/Markt (U-Tunnel)
    ],
    "kaserne": [
        "de:05314:61115",   # Bertha-von-Suttner-Pl./Beethovenhaus
        "de:05314:61114",   # Stadthaus
    ],
    "b56": [
        "de:05314:61197",   # Friedensplatz
        "de:05314:61122",   # Thomas-Mann-Str.
    ],
    "beuel": [
        "de:05314:65116",   # Beuel Rathaus (529,530,537,640 über Kennedy-Brücke)
        "de:05314:65101",   # Beuel Bahnhof
    ],
    "_innenstadt": [        # Gesamtbild (kein eigener Korridor im Widget)
        "22002667",
        "22000687",
        "22001142",
    ],
}

EFA_BASE = "https://efa.vrr.de/vrr/XML_DM_REQUEST"


def _fetch_stop_delays(stop_id: str) -> list[float]:
    """Gibt Liste der Verspätungsminuten für eine Haltestelle zurück."""
    r = requests.get(EFA_BASE, params={
        "outputFormat": "JSON", "type_dm": "stop", "name_dm": stop_id,
        "mode": "direct", "useRealtime": 1, "limit": 20, "depType": "stopEvents",
    }, timeout=15)
    deps = r.json().get("departureList", [])
    delays = []
    for dep in deps:
        dt_plan = dep.get("dateTime", {})
        dt_real = dep.get("realDateTime", dep.get("dateTime", {}))
        try:
            def to_dt(dt):
                return datetime(int(dt["year"]), int(dt["month"]), int(dt["day"]),
                                int(dt["hour"]), int(dt["minute"]), tzinfo=timezone.utc)
            d = (to_dt(dt_real) - to_dt(dt_plan)).total_seconds() / 60
            delays.append(round(d, 1))
        except Exception:
            pass
    return delays


# EFA liefert vereinzelt Artefakte (Zusatzfahrten, Soll-Zeiten aus der Vergangenheit)
# mit bis zu 417 Min. Sie zerstoeren jeden Mittelwert. Werte ausserhalb dieses
# Fensters werden als Artefakt verworfen. Begruendung/Beleg: Analyse 2026-07-20.
ARTIFACT_MIN = -5.0
ARTIFACT_MAX = 60.0


def _delay_stats(delays: list[float]) -> dict:
    """Robuste Verspätungs-Kennzahlen inkl. Artefakt-Filter und bedingter
    Verspätung (wie hoch, WENN verspätet)."""
    delays = [d for d in delays if ARTIFACT_MIN <= d <= ARTIFACT_MAX]
    if not delays:
        return {"n": 0, "error": "no data"}
    late = [d for d in delays if d > 1]
    n = len(delays)
    return {
        "n":                len(delays),
        "median_delay_min": round(statistics.median(delays), 1),
        "avg_delay_min":    round(statistics.mean(delays), 2),
        "pct_on_time":      round(sum(1 for d in delays if d <= 1) / n * 100, 1),
        "pct_over_3min":    round(sum(1 for d in delays if d > 3) / n * 100, 1),
        "pct_over_5min":    round(sum(1 for d in delays if d > 5) / n * 100, 1),
        # Verspätung, WENN verspätet (>1 Min) — robuster Median + Mittel:
        "delay_when_late_median": round(statistics.median(late), 1) if late else 0,
        "delay_when_late_avg":    round(statistics.mean(late), 1)   if late else 0,
    }


def fetch_oepnv_delays() -> dict:
    all_delays: list[float] = []
    per_corridor: dict[str, list[float]] = {}

    for corridor, stops in STOPS_BY_CORRIDOR.items():
        cor_delays: list[float] = []
        for stop_id in stops:
            try:
                delays = _fetch_stop_delays(stop_id)
                cor_delays.extend(delays)
                all_delays.extend(delays)
            except Exception as e:
                print(f"  EFA FEHLER {stop_id}: {e}")
        per_corridor[corridor] = cor_delays

    if not all_delays:
        return {"error": "no data"}

    result = _delay_stats(all_delays)
    result["n_departures"] = result.pop("n")   # I6-Schema-Kompatibilität
    # Per-Korridor (ohne _innenstadt-Pseudo-Korridor)
    for cor in ("stadtbahn", "kaserne", "b56", "beuel"):
        result[cor] = _delay_stats(per_corridor.get(cor, []))

    return result


# ── MIV: bundesstaustadt.de ──────────────────────────────────────────────────
MIV_CSV_COLUMNS = [
    "collected_at", "route_id", "route_name",
    "current_min", "avg_min", "delta_min", "status",
]


def archive_miv(miv_data: dict, collected_at: str):
    """Hängt MIV-Messwerte an miv_YYYY-MM.csv an (analog zu delays_*.csv)."""
    if "error" in miv_data:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"miv_{collected_at[:7]}.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MIV_CSV_COLUMNS)
        if new:
            w.writeheader()
        for rid, vals in miv_data.items():
            w.writerow({
                "collected_at": collected_at,
                "route_id":     rid,
                "route_name":   vals.get("name", ""),
                "current_min":  vals.get("current_min", ""),
                "avg_min":      vals.get("avg_min", ""),
                "delta_min":    vals.get("delta_min", ""),
                "status":       vals.get("status", ""),
            })


def fetch_miv() -> dict:
    try:
        r = requests.get("https://bundesstaustadt.de/api/routes/stats", timeout=15)
        routes = {ro["id"]: ro for ro in r.json().get("routes", [])}
        result = {}
        for rid, name in MIV_ROUTE_IDS.items():
            ro = routes.get(rid, {})
            cur = ro.get("current_duration")
            avg = ro.get("average_duration")
            result[str(rid)] = {
                "name":         name,
                "current_min":  cur,
                "avg_min":      avg,
                "delta_min":    round(cur - avg, 1) if cur and avg else None,
                "status":       ro.get("status"),
            }
        return result
    except Exception as e:
        print(f"  MIV FEHLER: {e}")
        return {"error": str(e)}


# ── 7-Tage-Schnitt aus CSV ────────────────────────────────────────────────────
def compute_7day_avg() -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    delays_by_corridor: dict[str, list[float]] = {}
    all_delays: list[float] = []
    by_hour: dict[int, list[float]] = {}
    n_days: set[str] = set()

    for csv_path in sorted(DATA_DIR.glob("delays_*.csv")):
        try:
            with open(csv_path, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    try:
                        ts = datetime.fromisoformat(row["collected_at"].replace("Z", "+00:00"))
                        if ts < cutoff:
                            continue
                        d = float(row["delay_min"])
                        if not (ARTIFACT_MIN <= d <= ARTIFACT_MAX):
                            continue   # Artefakt verwerfen
                        n_days.add(ts.date().isoformat())
                        cor = row["corridor"]
                        delays_by_corridor.setdefault(cor, []).append(d)
                        all_delays.append(d)
                        by_hour.setdefault(ts.hour, []).append(d)
                    except Exception:
                        pass
        except Exception:
            pass

    MIN_DAYS = 7
    if len(n_days) < MIN_DAYS:
        return {"available": False, "days_collected": len(n_days), "min_days": MIN_DAYS}

    result = {"available": True, "days_collected": len(n_days)}
    for cor, vals in delays_by_corridor.items():
        result[cor] = _delay_stats(vals)
    result["gesamt"] = _delay_stats(all_delays)

    # Tageszeit-Kurve (aggregiert über alle Korridore): pünktlich-Anteil und
    # Verspätung-wenn-verspätet je Stunde. Antwort auf "wann lohnt der ÖPNV".
    byhour: dict[str, dict] = {}
    for h in sorted(by_hour):
        v = by_hour[h]
        late = [x for x in v if x > 1]
        byhour[str(h)] = {
            "n":                   len(v),
            "pct_on_time":         round(sum(1 for x in v if x <= 1) / len(v) * 100),
            "delay_when_late_avg": round(statistics.mean(late), 1) if late else 0,
        }
    result["byhour"] = byhour
    return result


# ── ÖPNV: gleitendes Kurzfenster (letzte N Stunden) ─────────────────────────
def compute_recent_oepnv(hours: int = 2) -> dict:
    """Verspätungslage der letzten N Stunden — reflektiert die AKTUELLE Situation
    (Berufsverkehr vs. Nacht), im Gegensatz zum geglätteten 7-Tage-Schnitt.
    Genug Messzeilen (~24 Läufe) für eine stabile 'wenn verspätet'-Kennzahl."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    delays: list[float] = []
    for csv_path in sorted(DATA_DIR.glob("delays_*.csv")):
        try:
            with open(csv_path, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    try:
                        ts = datetime.fromisoformat(row["collected_at"].replace("Z", "+00:00"))
                        if ts < cutoff:
                            continue
                        d = float(row["delay_min"])
                        if ARTIFACT_MIN <= d <= ARTIFACT_MAX:
                            delays.append(d)
                    except Exception:
                        pass
        except Exception:
            pass
    if not delays:
        return {"available": False, "window_hours": hours, "n": 0}
    s = _delay_stats(delays)
    s["available"] = True
    s["window_hours"] = hours
    return s


# ── MIV 7-Tage-Schnitt aus CSV ───────────────────────────────────────────────
def compute_miv_7day_avg() -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    currents: list[float] = []
    deltas: list[float] = []
    n_days: set[str] = set()

    for csv_path in sorted(DATA_DIR.glob("miv_*.csv")):
        try:
            with open(csv_path, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    try:
                        if int(row.get("route_id", -1)) != MIV_PRIMARY:
                            continue
                        ts = datetime.fromisoformat(row["collected_at"].replace("Z", "+00:00"))
                        if ts < cutoff:
                            continue
                        # Nur Tageszeiten 6–20h (kein Nacht-Bias)
                        if not (6 <= ts.hour < 20):
                            continue
                        n_days.add(ts.date().isoformat())
                        if row.get("current_min"):
                            currents.append(float(row["current_min"]))
                        if row.get("delta_min"):
                            deltas.append(float(row["delta_min"]))
                    except Exception:
                        pass
        except Exception:
            pass

    MIN_DAYS = 7
    if len(n_days) < MIN_DAYS:
        return {"available": False, "days_collected": len(n_days), "min_days": MIN_DAYS}

    return {
        "available": True,
        "days_collected": len(n_days),
        "avg_current_min": round(statistics.mean(currents), 1) if currents else None,
        "avg_delta_min":   round(statistics.mean(deltas), 2)   if deltas   else None,
        "n": len(currents),
    }


# ── Zusammenführen und schreiben ──────────────────────────────────────────────
def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Erstelle current.json ({now})")

    oepnv    = fetch_oepnv_delays()
    miv      = fetch_miv()
    archive_miv(miv, now)
    avg_7d   = compute_7day_avg()
    oepnv_2h = compute_recent_oepnv(2)
    miv_7d   = compute_miv_7day_avg()

    out = {
        "updated_at": now,
        "oepnv_aktuell": oepnv,
        "oepnv_2h": oepnv_2h,
        "miv": miv,
        "oepnv_7tage": avg_7d,
        "miv_7tage": miv_7d,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"  → {OUT_FILE} geschrieben")
    print(f"  ÖPNV: Ø {oepnv.get('avg_delay_min','?')} Min, {oepnv.get('n_departures','?')} Abfahrten")
    primary = miv.get(str(MIV_PRIMARY), {})
    print(f"  MIV (Route {MIV_PRIMARY}): {primary.get('current_min','?')} Min (Ø {primary.get('avg_min','?')})")
    miv_path = DATA_DIR / f"miv_{now[:7]}.csv"
    print(f"  MIV archiviert → {miv_path}")
    print(f"  7-Tage-Daten: {avg_7d.get('days_collected', 0)} Tage gesammelt")


if __name__ == "__main__":
    main()
