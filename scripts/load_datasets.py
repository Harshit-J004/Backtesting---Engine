import os
import sys
import struct
import argparse
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"

DATASET_CATEGORIES = {
    "future": DATASETS_DIR / "Future",
    "spot": DATASETS_DIR / "Spot",
    "stocks": DATASETS_DIR / "NSE_Stocks",
    "fii_dii": DATASETS_DIR / "fii_dii_participant_data.csv",
}

# Binary format: Q(8) + I(4) + f(4)*5 + I(4)*2 = 40 bytes
PACK_FORMAT = '<QIfffffII'
RECORD_SIZE = struct.calcsize(PACK_FORMAT)


def get_dataset_catalog() -> Dict[str, Dict]:
    catalog = {}
    
    future_dir = DATASET_CATEGORIES["future"]
    if future_dir.exists():
        for f in future_dir.glob("*.csv"):
            name = f.stem.lower().replace("_data", "").replace("_futures", "_fut")
            catalog[name] = {"path": str(f), "category": "future", "display_name": f.stem}
    
    spot_dir = DATASET_CATEGORIES["spot"]
    if spot_dir.exists():
        for f in spot_dir.glob("*.csv"):
            name = f.stem.lower().replace("_data", "") + "_spot"
            catalog[name] = {"path": str(f), "category": "spot", "display_name": f.stem}
    
    stocks_dir = DATASET_CATEGORIES["stocks"]
    if stocks_dir.exists():
        for f in stocks_dir.glob("*.csv"):
            name = f.stem.lower().replace("_data", "")
            catalog[name] = {"path": str(f), "category": "stocks", "display_name": f.stem}
    
    raw_dir = PROJECT_ROOT / "data" / "raw"
    if raw_dir.exists():
        for f in raw_dir.glob("*.csv"):
            name = f.stem.lower()
            if name not in catalog:
                catalog[name] = {"path": str(f), "category": "raw", "display_name": f.stem}
    
    return catalog


def list_datasets() -> None:
    catalog = get_dataset_catalog()
    print("\n" + "=" * 60)
    print("FELIX BACKTESTER - AVAILABLE DATASETS")
    print("=" * 60)
    
    categories = {}
    for name, info in catalog.items():
        cat = info["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append((name, info))
    
    for cat, label in [("future", "FUTURES"), ("spot", "SPOT"), ("stocks", "STOCKS"), ("raw", "RAW")]:
        if cat in categories:
            print(f"\n{label}\n" + "-" * 40)
            for name, info in sorted(categories[cat]):
                print(f"  • {name:30s} [{info['display_name']}]")
    
    print(f"\n{'=' * 60}\nTotal: {len(catalog)}\n{'=' * 60}\n")


def load_ohlcv(dataset_name: str, start_date: Optional[str] = None, 
               end_date: Optional[str] = None, limit: Optional[int] = None) -> pd.DataFrame:
    catalog = get_dataset_catalog()
    if dataset_name not in catalog:
        return None
    
    info = catalog[dataset_name]
    print(f"Loading {dataset_name} from {info['category']}...")
    df = pd.read_csv(info["path"], nrows=limit)
    df.columns = df.columns.str.lower().str.strip()
    
    if info["category"] == "future" and "date" in df.columns and "time" in df.columns:
        df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"], format="%d/%m/%y %H:%M:%S", errors="coerce")
    elif "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    elif "timestamp" in df.columns:
        df["datetime"] = pd.to_datetime(df["timestamp"], errors="coerce")
    elif "date" in df.columns:
        df["datetime"] = pd.to_datetime(df["date"], errors="coerce")
    
    if "datetime" in df.columns and df["datetime"].dt.tz is not None:
        df["datetime"] = df["datetime"].dt.tz_localize(None)
    
    for col in ["close", "price", "last", "ltp"]:
        if col in df.columns:
            df["close"] = df[col]
            break
    
    for col in ["open", "high", "low"]:
        if col not in df.columns and "close" in df.columns:
            df[col] = df["close"]
    if "volume" not in df.columns:
        df["volume"] = 1000
    
    if "datetime" in df.columns:
        df = df.dropna(subset=["datetime"])
        if start_date:
            df = df[df["datetime"] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df["datetime"] <= pd.to_datetime(end_date)]
        df = df.sort_values("datetime").reset_index(drop=True)
        print(f"  Loaded {len(df):,} records from {df['datetime'].min()} to {df['datetime'].max()}")
    else:
        print(f"  Loaded {len(df):,} records")
    
    return df


def create_sample_data(output_path: str, num_ticks: int = 98280) -> None:
    print(f"Creating sample tick data... Format: {PACK_FORMAT}, size: {RECORD_SIZE} bytes")
    
    base_timestamp = int(datetime(2023, 1, 1).timestamp() * 1e9)
    base_price = 2500.0
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    np.random.seed(42)
    
    with open(output_path, 'wb') as f:
        price = base_price
        for i in range(num_ticks):
            price += np.random.randn() * 2.0
            price = max(price, 100.0)
            
            record = struct.pack(PACK_FORMAT,
                int(base_timestamp + i * 60_000_000_000),
                1,
                float(price),
                float(price - 0.05),
                float(price + 0.05),
                float(np.random.randint(100, 1000)),
                float(np.random.randint(100, 1000)),
                int(np.random.randint(1000, 10000)),
                0
            )
            f.write(record)
    
    file_size = os.path.getsize(output_path)
    print(f"Created {file_size // RECORD_SIZE:,} ticks in {output_path} ({file_size:,} bytes)")


def convert_to_binary(df: pd.DataFrame, symbol_id: int, output_file: str) -> None:
    print(f"Converting {len(df):,} records... Format: {PACK_FORMAT}, size: {RECORD_SIZE} bytes")
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, "wb") as f:
        for _, row in df.iterrows():
            ts = int(row["datetime"].timestamp() * 1e9) if "datetime" in row and pd.notna(row["datetime"]) else 0
            price = float(row.get("close", row.get("price", 0)))
            
            record = struct.pack(PACK_FORMAT,
                int(ts),
                int(symbol_id),
                float(price),
                float(row.get("bid", price - 0.05)),
                float(row.get("ask", price + 0.05)),
                float(row.get("bid_size", 100)),
                float(row.get("ask_size", 100)),
                int(row.get("volume", 1000)),
                0
            )
            f.write(record)
    
    file_size = output_path.stat().st_size
    print(f"  ✓ Saved {file_size // RECORD_SIZE:,} records to {output_file} ({file_size:,} bytes)")



def load_btc_full_data(output_path: str, start_year: int = 2021, end_year: int = 2025) -> None:
    btc_dir = DATASETS_DIR / "BTCUSDT_1m_data"
    all_dfs = []
    
    print(f"Loading BTC data from {start_year} to {end_year}...")
    
    for year in range(start_year, end_year + 1):
        file_patterns = [f"BTC_USDT_1m_{year}.csv", f"BTCUSDT_{year}.csv"]
        found = False
        for pattern in file_patterns:
            fpath = btc_dir / pattern
            if fpath.exists():
                print(f"  Reading: {fpath.name}")
                df = pd.read_csv(fpath)
                df.columns = df.columns.str.lower().str.strip()
                all_dfs.append(df)
                found = True
                break
        if not found:
            print(f"  [WARN] No file found for year {year}")

    if not all_dfs:
        print("No BTC data files found!")
        return

    full_df = pd.concat(all_dfs, ignore_index=True)
    
    # Normalize columns
    if "open_time" in full_df.columns:
        # 13 digit timestamp = ms
        full_df["datetime"] = pd.to_datetime(full_df["open_time"], unit='ms')
    elif "date" in full_df.columns and "time" in full_df.columns:
        # Try YYYY-MM-DD
        full_df["datetime"] = pd.to_datetime(full_df["date"] + " " + full_df["time"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    elif "timestamp" in full_df.columns:
        # Check if timestamp is ms or seconds
         # Assuming seconds if year < 3000, else ms
        sample = full_df["timestamp"].iloc[0]
        if sample > 3000000000: # ms
             full_df["datetime"] = pd.to_datetime(full_df["timestamp"], unit='ms')
        else:
             full_df["datetime"] = pd.to_datetime(full_df["timestamp"], unit='s')
    
    # Filter valid dates
    full_df = full_df.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    
    print(f"Merged Data: {len(full_df):,} records ({full_df['datetime'].min()} to {full_df['datetime'].max()})")
    
    convert_to_binary(full_df, symbol_id=1, output_file=output_path)


def load_reliance_data(output_path: str) -> None:
    df = load_ohlcv("reliance")
    if df is None or len(df) == 0:
        for name in ["RELIANCE", "reliance_data"]:
            df = load_ohlcv(name.lower())
            if df is not None and len(df) > 0:
                break
    
    if df is None or len(df) == 0:
        print("No data file found. Creating sample data...")
        create_sample_data(output_path)
        return
    
    convert_to_binary(df, symbol_id=1, output_file=output_path)


def main():
    parser = argparse.ArgumentParser(description="Felix Backtester - Dataset Loader")
    parser.add_argument("--list", "-l", action="store_true", help="List datasets")
    parser.add_argument("--dataset", "-d", type=str, help="Dataset name")
    parser.add_argument("--output", "-o", type=str, default="data/processed/reliance.bin")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--symbol-id", type=int, default=1)
    parser.add_argument("--sample", action="store_true", help="Generate sample data")
    parser.add_argument("--preview", type=int, help="Preview N rows")
    args = parser.parse_args()
    
    assert RECORD_SIZE == 40, f"RECORD_SIZE should be 40, got {RECORD_SIZE}"
    
    if args.list:
        list_datasets()
    elif args.sample:
        create_sample_data(args.output)
    elif args.dataset:
        if args.dataset.lower() == "btc_full":
            load_btc_full_data(args.output)
        elif args.dataset.lower() == "reliance":
            load_reliance_data(args.output)
        else:
            df = load_ohlcv(args.dataset, args.start, args.end, args.preview)
            if df is None or len(df) == 0:
                print(f"Dataset '{args.dataset}' not found. Use --list or --sample.")
            elif args.preview:
                print(df.head(args.preview).to_string())
            else:
                convert_to_binary(df, args.symbol_id, args.output)
                print(f"\n✓ Ready: {args.output}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()