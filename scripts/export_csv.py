"""
Export raw_series from Supabase to a wide-format CSV.

Usage:
    python scripts/export_csv.py                  # all series
    python scripts/export_csv.py --start 2020-01-01
    python scripts/export_csv.py --series UNRATE BAA10Y
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flowmacro.config import settings
from supabase import create_client
import pandas as pd


def _client():
    return create_client(settings.supabase_url, settings.supabase_key)


def list_series(client) -> list[str]:
    rows = client.table("raw_series").select("series_id").execute().data
    return sorted({r["series_id"] for r in rows})


def fetch_series(client, series_id: str, start: str | None) -> pd.Series:
    PAGE = 1000
    all_rows, offset = [], 0
    while True:
        q = client.table("raw_series").select("date,value").eq("series_id", series_id)
        if start:
            q = q.gte("date", start)
        result = q.order("date").range(offset, offset + PAGE - 1).execute()
        all_rows.extend(result.data)
        if len(result.data) < PAGE:
            break
        offset += PAGE
    if not all_rows:
        return pd.Series(dtype=float, name=series_id)
    df = pd.DataFrame(all_rows)
    return df.set_index(pd.to_datetime(df["date"]))["value"].rename(series_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start",  default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--series", nargs="*", default=None, help="Series IDs to export (default: all)")
    parser.add_argument("--out",    default=None, help="Output CSV path (default: auto-named)")
    args = parser.parse_args()

    client = _client()
    series_ids = args.series or list_series(client)
    print(f"Exporting {len(series_ids)} series: {', '.join(series_ids)}")

    frames = []
    for sid in series_ids:
        s = fetch_series(client, sid, args.start)
        if not s.empty:
            frames.append(s)
        print(f"  {sid}: {len(s)} rows")

    if not frames:
        print("No data found.")
        return

    wide = pd.concat(frames, axis=1).sort_index()
    wide.index.name = "date"

    out_path = args.out or f"{datetime.now().strftime('%Y-%m-%dT%H-%M')}_export.csv"
    wide.to_csv(out_path)
    print(f"\nSaved: {out_path}  ({len(wide)} rows x {len(wide.columns)} columns)")


if __name__ == "__main__":
    main()
