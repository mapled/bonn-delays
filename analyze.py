#!/usr/bin/env python3
"""
Basisanalyse: Lädt alle delays_YYYY-MM.csv aus data/ und zeigt
Verspätungsverteilung pro Linie, Haltestelle und Tageszeit.

Verwendung:
  pip install pandas matplotlib
  python analyze.py [--month 2026-06]
"""

import argparse
from pathlib import Path

import pandas as pd

DATA_DIR = Path("data")

def load(month: str | None = None) -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("delays_*.csv"))
    if month:
        files = [f for f in files if month in f.name]
    if not files:
        raise FileNotFoundError(f"Keine CSV-Dateien in {DATA_DIR}/")
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    df["collected_at"] = pd.to_datetime(df["collected_at"], utc=True)
    df["hour"] = df["collected_at"].dt.hour
    df["dow"]  = df["collected_at"].dt.dayofweek  # 0=Mo
    df["delay_min"] = df["delay_sec"] / 60
    return df

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="Filter auf YYYY-MM (default: alle)")
    parser.add_argument("--route", help="Nur diese Route-ID anzeigen")
    args = parser.parse_args()

    df = load(args.month)
    if args.route:
        df = df[df["route_id"] == args.route]

    print(f"\n{'─'*60}")
    print(f"Datensätze gesamt:   {len(df):>10,}")
    print(f"Zeitraum:            {df['collected_at'].min()} – {df['collected_at'].max()}")
    print(f"Linien:              {df['route_id'].nunique()}")
    print(f"Haltestellen:        {df['stop_id'].nunique()}")

    print(f"\n── Verspätung nach Linie (Median / 90. Perzentil) ──")
    tbl = (
        df.groupby("route_id")["delay_min"]
        .agg(n="count", median="median", p90=lambda x: x.quantile(0.9), max="max")
        .sort_values("p90", ascending=False)
        .head(20)
    )
    print(tbl.to_string(float_format="{:.1f}".format))

    print(f"\n── Verspätung nach Stunde (alle Linien, Median Minuten) ──")
    by_hour = df.groupby("hour")["delay_min"].median().round(1)
    for h, v in by_hour.items():
        bar = "█" * int(max(v, 0))
        print(f"  {h:02d}h  {v:5.1f} min  {bar}")

    print(f"\n── Top-10 Haltestellen mit höchster Verspätung (p90) ──")
    tbl2 = (
        df.groupby("stop_id")["delay_min"]
        .agg(n="count", median="median", p90=lambda x: x.quantile(0.9))
        .query("n > 10")
        .sort_values("p90", ascending=False)
        .head(10)
    )
    print(tbl2.to_string(float_format="{:.1f}".format))

if __name__ == "__main__":
    main()
