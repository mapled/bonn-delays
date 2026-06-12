#!/usr/bin/env python3
"""
Hilfsskript: Findet Stop-IDs auf einem Straßenabschnitt aus dem statischen GTFS-Feed.
Läuft einmalig lokal, um MONITOR_STOPS zu befüllen.

Verwendung:
  pip install requests
  python find_stops.py --gtfs VRS_GTFS.zip --street "Kölnstraße" --street "B56" --street "Bornheimer"

Gibt kommaseparierte Stop-IDs aus, die du in GitHub Secrets als MONITOR_STOPS einträgst.
"""

import argparse
import csv
import io
import zipfile

import requests

VRS_GTFS_URL = "https://www.vrs.de/fileadmin/Dokumente/GTFS/VRS_GTFS.zip"

def load_stops_from_zip(path_or_url: str) -> list[dict]:
    if path_or_url.startswith("http"):
        print(f"Lade GTFS von {path_or_url} …")
        r = requests.get(path_or_url, timeout=120, stream=True)
        r.raise_for_status()
        data = r.content
    else:
        with open(path_or_url, "rb") as f:
            data = f.read()

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        with z.open("stops.txt") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            return list(reader)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gtfs", default=VRS_GTFS_URL,
                        help="Pfad oder URL zur GTFS-ZIP (default: VRS)")
    parser.add_argument("--street", action="append", required=True,
                        help="Straßennamen-Fragment(e) zum Suchen (wiederholen für mehrere)")
    args = parser.parse_args()

    stops = load_stops_from_zip(args.gtfs)
    keywords = [s.lower() for s in args.street]

    matches = [
        s for s in stops
        if any(kw in s.get("stop_name", "").lower() for kw in keywords)
    ]

    if not matches:
        print("Keine Haltestellen gefunden. Andere Suchbegriffe versuchen?")
        return

    print(f"\n{len(matches)} Haltestellen gefunden:\n")
    ids = []
    for s in sorted(matches, key=lambda x: x.get("stop_name", "")):
        print(f"  {s['stop_id']:20s}  {s['stop_name']}")
        ids.append(s["stop_id"])

    print(f"\nMONITOR_STOPS=")
    print(",".join(ids))

if __name__ == "__main__":
    main()
