#!/usr/bin/env python3
"""Check the Kaggle 'Pharma sales data' files and build the Power BI-ready CSV.

Usage:
    python scripts/clean_and_aggregate.py --input-dir path/to/kaggle_csvs --output-dir data

Needs salesdaily.csv in --input-dir. saleshourly.csv and salesmonthly.csv are
optional and only used for the reconciliation checks.
"""
import argparse
from pathlib import Path

import pandas as pd

# Short labels based on the ATC classification (check against the WHO ATC index before quoting)
CATEGORIES = {
    "M01AB": "Anti-inflammatory (acetic acid)",
    "M01AE": "Anti-inflammatory (propionic acid)",
    "N02BA": "Analgesic (salicylic acid)",
    "N02BE": "Analgesic (paracetamol-type)",
    "N05B": "Anxiolytics",
    "N05C": "Hypnotics & sedatives",
    "R03": "Airway disease drugs",
    "R06": "Antihistamines",
}
ATC_MAIN_GROUP = {"M": "Musculo-skeletal system", "N": "Nervous system", "R": "Respiratory system"}
CODES = list(CATEGORIES)


def monthly_from_daily(daily: pd.DataFrame) -> pd.DataFrame:
    return daily.set_index("date")[CODES].resample("ME").sum()


def quality_report(input_dir: Path, daily: pd.DataFrame) -> None:
    print("== Data quality checks ==")
    print(f"daily rows: {len(daily)}, range: {daily.date.min().date()} to {daily.date.max().date()}")
    print(f"null cells: {int(daily[CODES].isna().sum().sum())}, duplicate dates: {int(daily.date.duplicated().sum())}")
    missing = pd.date_range(daily.date.min(), daily.date.max()).difference(daily.date)
    print(f"missing calendar days: {len(missing)}")
    zero_days = int((daily[CODES].sum(axis=1) == 0).sum())
    print(f"days with zero sales in every category: {zero_days}")

    hourly_path = input_dir / "saleshourly.csv"
    if hourly_path.exists():
        h = pd.read_csv(hourly_path)
        h["date"] = pd.to_datetime(h["datum"], format="%m/%d/%Y %H:%M")
        hd = h.set_index("date")[CODES].resample("D").sum()
        diff = abs(hd.reindex(daily.date).to_numpy() - daily[CODES].to_numpy()).max()
        print(f"hourly vs daily, max abs difference: {diff:.4f}")

    monthly_path = input_dir / "salesmonthly.csv"
    if monthly_path.exists():
        m = pd.read_csv(monthly_path)
        m["date"] = pd.to_datetime(m["datum"]) + pd.offsets.MonthEnd(0)
        mine = monthly_from_daily(daily).sum(axis=1)
        theirs = m.set_index("date")[CODES].sum(axis=1)
        ratio = (theirs / mine.reindex(theirs.index)).sub(1).abs()
        print(f"months where salesmonthly.csv differs from the daily roll-up by >1%: {int((ratio > 0.01).sum())} of {len(ratio)}")
        print("=> using the daily file as the source of truth")


def build_powerbi_csv(daily: pd.DataFrame) -> pd.DataFrame:
    monthly = monthly_from_daily(daily)
    last_day = daily.date.max()
    if last_day != last_day + pd.offsets.MonthEnd(0):  # last month is incomplete
        print(f"dropping partial month {last_day:%Y-%m} (data ends {last_day.date()})")
        monthly = monthly.iloc[:-1]
    long = monthly.reset_index().melt(id_vars="date", var_name="Category Code", value_name="Units Sold")
    long["Month"] = long["date"].dt.to_period("M").dt.to_timestamp().dt.strftime("%Y-%m-%d")  # first of month, ISO
    long["Category Name"] = long["Category Code"].map(CATEGORIES)
    long["ATC Main Group"] = long["Category Code"].str[0].map(ATC_MAIN_GROUP)
    long["Units Sold"] = long["Units Sold"].round(2)
    long["_order"] = long["Category Code"].map({c: i for i, c in enumerate(CODES)})
    long = long.sort_values(["Month", "_order"])
    return long[["Month", "Category Code", "Category Name", "ATC Main Group", "Units Sold"]]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, default=Path("data"))
    args = p.parse_args()

    daily = pd.read_csv(args.input_dir / "salesdaily.csv")
    daily["date"] = pd.to_datetime(daily["datum"], format="%m/%d/%Y")
    quality_report(args.input_dir, daily)

    out = build_powerbi_csv(daily)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / "pharma_sales_powerbi.csv"
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows, {out['Month'].nunique()} months, total units {out['Units Sold'].sum():,.1f})")


if __name__ == "__main__":
    main()
