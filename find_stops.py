#!/usr/bin/env python3
"""
Findet EFA-Stop-IDs für Haltestellen in Bonn per Namenssuche.
Läuft einmalig lokal — gibt STOP_IDS-Wert für GitHub Secrets aus.

Verwendung:
  pip install requests
  python find_stops.py "Kölnstraße"
  python find_stops.py "B56"
  python find_stops.py "Bornheimer"
"""

import sys
import requests

EFA_BASE = "https://efa.vrr.de/vrr/XML_STOPFINDER_REQUEST"

def find(query: str) -> list[dict]:
    params = {
        "outputFormat":      "JSON",
        "coordOutputFormat": "WGS84[DD.DDDDD]",
        "type_sf":           "any",
        "name_sf":           query,
        "anyObjFilter_sf":   2,  # nur Haltestellen
    }
    r = requests.get(EFA_BASE, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    try:
        points = data["stopFinder"]["points"]
        if isinstance(points, dict):
            points = [points["point"]] if "point" in points else []
        return points
    except (KeyError, TypeError):
        return []

def main():
    queries = sys.argv[1:] or ["Kölnstraße", "Bornheimer"]
    all_ids = []

    for q in queries:
        print(f"\nSuche: {q!r}")
        stops = find(q)
        if not stops:
            print("  — keine Treffer")
            continue
        for s in stops:
            try:
                sid  = s.get("ref", {}).get("id", s.get("id", "?"))
                name = s.get("name", s.get("anyName", "?"))
                city = s.get("ref", {}).get("city", "")
                print(f"  {sid:20s}  {name}  ({city})")
                all_ids.append(sid)
            except Exception:
                pass

    if all_ids:
        print(f"\nSTOP_IDS=")
        print(",".join(dict.fromkeys(all_ids)))  # Duplikate raus, Reihenfolge behalten

if __name__ == "__main__":
    main()
