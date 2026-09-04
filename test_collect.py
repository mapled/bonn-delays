#!/usr/bin/env python3
"""Tests fuer collect.py — Schwerpunkt: das neue Feld planned_ts_local.

Hintergrund (04.09.2026): `planned_ts` traegt Ortszeit mit dem falschen Label
`+00:00`. Das Feld bleibt aus Kompatibilitaetsgruenden unveraendert; daneben
tritt `planned_ts_local` mit korrektem Europe/Berlin-Offset.

Lauf:  python3 -m pytest test_collect.py -q     (oder: python3 test_collect.py)
Kein Netzzugriff — parse_departures bekommt eine EFA-Antwort als dict.
"""
import csv
import tempfile
from pathlib import Path

import collect


def _dep(y, mo, d, h, mi, *, real=None):
    """Minimale EFA-Abfahrt; real=(h,mi) setzt eine abweichende Ist-Zeit."""
    plan = {"year": str(y), "month": str(mo), "day": str(d),
            "hour": str(h), "minute": str(mi)}
    dep = {"servingLine": {"number": "603", "direction": "Bonn Hbf"},
           "stopName": "Bonn Stadthaus", "realtimeStatus": "", "dateTime": plan}
    if real is not None:
        rh, rm = real
        dep["realDateTime"] = dict(plan, hour=str(rh), minute=str(rm))
    return dep


def _parse_one(dep):
    rows = collect.parse_departures({"departureList": [dep]},
                                    "de:05314:61114", "Kasernenstr_bleibt",
                                    "2026-09-03T05:18:00Z")
    assert len(rows) == 1
    return rows[0]


# ── planned_ts bleibt exakt wie bisher ────────────────────────────────────────

def test_planned_ts_unveraendert():
    r = _parse_one(_dep(2026, 9, 3, 7, 18))
    assert r["planned_ts"] == "2026-09-03T07:18:00+00:00"


def test_delay_min_unveraendert():
    r = _parse_one(_dep(2026, 9, 3, 7, 18, real=(7, 21)))
    assert r["delay_min"] == 3.0


# ── neues Feld planned_ts_local ──────────────────────────────────────────────

def test_local_sommerzeit_hat_plus_zwei():
    r = _parse_one(_dep(2026, 9, 3, 7, 18))
    assert r["planned_ts_local"] == "2026-09-03T07:18:00+02:00"


def test_local_winterzeit_hat_plus_eins():
    r = _parse_one(_dep(2026, 12, 3, 7, 18))
    assert r["planned_ts_local"] == "2026-12-03T07:18:00+01:00"


def test_wanduhrzeit_in_beiden_feldern_gleich():
    """Die Ziffern duerfen sich nicht verschieben — nur das Offset-Label."""
    r = _parse_one(_dep(2026, 9, 3, 7, 18))
    assert r["planned_ts"][:19] == r["planned_ts_local"][:19]


def test_dst_rueckstellung_nimmt_erste_stunde():
    """25.10.2026: 02:30 gibt es zweimal. Konvention: fold=0 → noch CEST."""
    r = _parse_one(_dep(2026, 10, 25, 2, 30))
    assert r["planned_ts_local"] == "2026-10-25T02:30:00+02:00"


def test_kaputte_zeit_liefert_none_statt_ausnahme():
    dep = _dep(2026, 9, 3, 7, 18)
    dep["dateTime"] = {"year": "2026"}          # unvollstaendig
    r = _parse_one(dep)
    assert r["planned_ts"] is None and r["planned_ts_local"] is None


# ── Schreiben: bestehende Dateien behalten ihr Schema ────────────────────────

LEGACY = ["collected_at", "corridor", "stop_id", "stop_name", "line",
          "direction", "planned_ts", "actual_ts", "delay_min", "status"]


def _rows():
    return [_parse_one(_dep(2026, 9, 3, 7, 18))]


def test_neue_datei_bekommt_die_neue_spalte():
    with tempfile.TemporaryDirectory() as d:
        collect.DATA_DIR = Path(d)
        collect.write_rows(_rows(), "2026-09-03T05:18:00Z")
        with open(Path(d) / "delays_2026-09.csv", encoding="utf-8") as f:
            rd = csv.reader(f)
            hdr = next(rd)
            row = next(rd)
        assert hdr == LEGACY + ["planned_ts_local"]
        assert len(row) == len(hdr)
        assert row[-1] == "2026-09-03T07:18:00+02:00"


def test_bestandsdatei_bleibt_bei_zehn_spalten():
    """Anhaengen an eine Datei mit altem Header darf keine 11. Spalte erzeugen —
    sonst passen Header und Zeilen nicht mehr zusammen."""
    with tempfile.TemporaryDirectory() as d:
        collect.DATA_DIR = Path(d)
        p = Path(d) / "delays_2026-09.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(LEGACY)
            w.writerow(["2026-09-01T00:00:00Z", "innenstadt", "22000687", "Bonn Hbf",
                        "62", "Bonn Ramersdorf", "2026-09-01T05:27:00+00:00",
                        "2026-09-01T05:27:00+00:00", "0.0", ""])
        collect.write_rows(_rows(), "2026-09-03T05:18:00Z")
        with open(p, encoding="utf-8") as f:
            zeilen = list(csv.reader(f))
        assert zeilen[0] == LEGACY
        assert all(len(z) == 10 for z in zeilen), [len(z) for z in zeilen]


def test_bestandsdatei_reihenfolge_bleibt_erhalten():
    """Auch bei abweichender Spaltenreihenfolge richtet sich der Writer nach
    dem Header der Datei, nicht nach COLUMNS."""
    with tempfile.TemporaryDirectory() as d:
        collect.DATA_DIR = Path(d)
        p = Path(d) / "delays_2026-09.csv"
        vertauscht = ["corridor", "collected_at"] + LEGACY[2:]
        with open(p, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(vertauscht)
        collect.write_rows(_rows(), "2026-09-03T05:18:00Z")
        with open(p, encoding="utf-8") as f:
            zeilen = list(csv.reader(f))
        assert zeilen[0] == vertauscht
        assert zeilen[1][0] == "Kasernenstr_bleibt"
        assert zeilen[1][1] == "2026-09-03T05:18:00Z"


if __name__ == "__main__":
    import sys
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as e:
                fails += 1
                print(f"  FAIL  {name}: {e}")
            except Exception as e:
                fails += 1
                print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print("fehlgeschlagen:", fails)
    sys.exit(1 if fails else 0)
