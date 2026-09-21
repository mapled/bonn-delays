#!/usr/bin/env python3
"""Tests fuer publish.py — Ersatzverkehr (BE…) darf nicht in den Stadtbahn-Wert.

Hintergrund (21.09.2026): Ab 17.09. fahren BE68-Ersatzbusse an den
Stadtbahn-Messhalten ab (6–10 % der Abfahrten). publish.py ordnete nach
Korridor, nicht nach Linie → Busverspaetungen im Stadtbahn-Balken.
Lauf: python3 -m pytest test_publish.py -q   (oder: python3 test_publish.py)
Kein Netzzugriff.
"""
import csv
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import publish

FIELDS = ["collected_at", "corridor", "stop_id", "stop_name", "line",
          "direction", "planned_ts", "actual_ts", "delay_min", "status"]


def _rows(n_days=8):
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(n_days):
        ts = (now - timedelta(days=i, minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append([ts, "stadtbahn", "x", "Hbf", "66", "", "", "", "0", "OK"])
        rows.append([ts, "stadtbahn", "x", "Hbf", "BE68", "", "", "", "20", "OK"])
        rows.append([ts, "kaserne", "y", "Stadthaus", "603", "", "", "", "2", "OK"])
    return rows


def _with_csv(fn):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "delays_2026-09.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(FIELDS); w.writerows(_rows())
        old = publish.DATA_DIR
        publish.DATA_DIR = Path(tmp)
        try:
            return fn()
        finally:
            publish.DATA_DIR = old


def test_ist_ersatzverkehr():
    assert publish._ist_ersatzverkehr("BE68")
    assert publish._ist_ersatzverkehr("be16")
    assert publish._ist_ersatzverkehr("SEV 18")
    assert not publish._ist_ersatzverkehr("66")
    assert not publish._ist_ersatzverkehr("E")      # Schuelerverstaerker
    assert not publish._ist_ersatzverkehr("")


def test_7tage_stadtbahn_ohne_ersatz():
    r = _with_csv(publish.compute_7day_avg)
    assert r["available"]
    assert r["stadtbahn"]["avg_delay_min"] == 0          # nur Linie 66
    assert r["stadtbahn_ersatz"]["avg_delay_min"] == 20  # additiver Schluessel
    assert r["gesamt"]["n"] == 21   # 7 Tage im Fenster x 3, Gesamt inkl. Ersatz


def test_2h_ersatz_zaehlt_als_bus():
    r = _with_csv(lambda: publish.compute_recent_oepnv(2))
    assert r["bahn"]["n"] == 1 and r["bahn"]["avg_delay_min"] == 0
    assert r["bus"]["n"] == 2                            # 603 + BE68
    assert r["n"] == 3


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f(); print("ok", name)
