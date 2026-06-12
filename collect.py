#!/usr/bin/env python3
"""
GTFS-RT Verspätungs-Logger — VRS/SWB/RSVG Bonn
Läuft alle 5 Minuten via GitHub Actions, schreibt Verspätungen je Haltestelle als CSV.

Konfiguration via Umgebungsvariablen (GitHub Secrets):
  GTFS_RT_URL       VRS TripUpdates-Feed (Protobuf)
  GTFS_RT_API_KEY   optional, als Bearer-Token
  MONITOR_STOPS     kommaseparierte Stop-IDs; leer = alle
  MONITOR_ROUTES    kommaseparierte Route-IDs; leer = alle (z.B. "600,601,SWB-18")
"""

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from google.transit import gtfs_realtime_pb2

# ── Konfiguration ──────────────────────────────────────────────────────────────
GTFS_RT_URL    = os.environ["GTFS_RT_URL"]
API_KEY        = os.environ.get("GTFS_RT_API_KEY", "")
MONITOR_STOPS  = set(s for s in os.environ.get("MONITOR_STOPS", "").split(",") if s)
MONITOR_ROUTES = set(r for r in os.environ.get("MONITOR_ROUTES", "").split(",") if r)
DATA_DIR       = Path(os.environ.get("DATA_DIR", "data"))

# ── Feed abrufen ───────────────────────────────────────────────────────────────
def fetch_feed() -> gtfs_realtime_pb2.FeedMessage:
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    r = requests.get(GTFS_RT_URL, headers=headers, timeout=30)
    r.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(r.content)
    return feed

# ── Rows extrahieren ───────────────────────────────────────────────────────────
def extract_rows(feed: gtfs_realtime_pb2.FeedMessage, collected_at: str) -> list[dict]:
    rows = []
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        route_id     = tu.trip.route_id
        trip_id      = tu.trip.trip_id
        direction_id = tu.trip.direction_id
        vehicle_id   = tu.vehicle.id if tu.HasField("vehicle") else ""

        if MONITOR_ROUTES and route_id not in MONITOR_ROUTES:
            continue

        for stu in tu.stop_time_update:
            stop_id      = stu.stop_id
            stop_seq     = stu.stop_sequence

            if MONITOR_STOPS and stop_id not in MONITOR_STOPS:
                continue

            # Ankunft bevorzugen, sonst Abfahrt
            if stu.HasField("arrival") and stu.arrival.HasField("time"):
                time_pred  = stu.arrival.time
                delay_sec  = stu.arrival.delay   # kann 0 sein wenn pünktlich
            elif stu.HasField("departure") and stu.departure.HasField("time"):
                time_pred  = stu.departure.time
                delay_sec  = stu.departure.delay
            else:
                continue

            scheduled = time_pred - delay_sec if delay_sec is not None else ""

            rows.append({
                "collected_at": collected_at,
                "route_id":     route_id,
                "trip_id":      trip_id,
                "direction_id": direction_id,
                "vehicle_id":   vehicle_id,
                "stop_id":      stop_id,
                "stop_sequence": stop_seq,
                "scheduled_ts": scheduled,
                "predicted_ts": time_pred,
                "delay_sec":    delay_sec,
            })
    return rows

# ── In Monats-CSV schreiben ────────────────────────────────────────────────────
COLUMNS = [
    "collected_at", "route_id", "trip_id", "direction_id",
    "vehicle_id", "stop_id", "stop_sequence",
    "scheduled_ts", "predicted_ts", "delay_sec",
]

def write_rows(rows: list[dict], collected_at: str):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    month = collected_at[:7]   # "YYYY-MM"
    path  = DATA_DIR / f"delays_{month}.csv"
    new   = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerows(rows)
    return path

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    feed = fetch_feed()
    rows = extract_rows(feed, now)
    if rows:
        path = write_rows(rows, now)
        print(f"{now}  {len(rows):>5} Zeilen → {path}")
    else:
        print(f"{now}  0 Zeilen (keine Treffer — Stops/Routes-Filter prüfen)")
    return len(rows)

if __name__ == "__main__":
    n = main()
    sys.exit(0 if n >= 0 else 1)
