"""
Felix Backtester - Dataset Loader
Unified loader for local NSE datasets: Futures, Spot, Stocks, and FII/DII data.
"""

import os
import sys
import struct
import argparse
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"


# Dataset categories and their paths
DATASET_CATEGORIES = {
    "future": DATASETS_DIR / "Future",
    "spot": DATASETS_DIR / "Spot",
    "stocks": DATASETS_DIR / "NSE_Stocks",
    "fii_dii": DATASETS_DIR / "fii_dii_participant_data.csv",
}


def get_dataset_catalog() -> Dict[str, Dict]:
    """
    Returns a catalog of all available datasets with metadata.
    """
    catalog = {}
    
    # Scan Future folder
    future_dir = DATASET_CATEGORIES["future"]
    if future_dir.exists():
        for f in future_dir.glob("*.csv"):
            name = f.stem.lower().replace("_data", "").replace("_futures", "_fut")
            catalog[name] = {
                "path": str(f),
                "category": "future",
                "display_name": f.stem,
            }
    
    # Scan Spot folder
    spot_dir = DATASET_CATEGORIES["spot"]
    if spot_dir.exists():
        for f in spot_dir.glob("*.csv"):
            name = f.stem.lower().replace("_data", "") + "_spot"
            catalog[name] = {
                "path": str(f),
                "category": "spot",
                "display_name": f.stem,
            }
    
    # Scan NSE_Stocks folder
    stocks_dir = DATASET_CATEGORIES["stocks"]
    if stocks_dir.exists():
        for f in stocks_dir.glob("*.csv"):
            name = f.stem.lower().replace("_data", "")
            catalog[name] = {
                "path": str(f),
                "category": "stocks",
                "display_name": f.stem,
            }
    
    # FII/DII data
    fii_dii_path = DATASET_CATEGORIES["fii_dii"]
    if fii_dii_path.exists():
        catalog["fii_dii"] = {
            "path": str(fii_dii_path),
            "category": "fii_dii",
            "display_name": "FII/DII Participant Data",
        }
    
    return catalog


def list_datasets() -> None:
    """Print all available datasets grouped by category."""
    catalog = get_dataset_catalog()
    
    print("\n" + "=" * 60)
    print("FELIX BACKTESTER - AVAILABLE DATASETS")
    print("=" * 60)
    
    # Group by category
    categories = {}
    for name, info in catalog.items():
        cat = info["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append((name, info))
    
    category_labels = {
        "future": "FUTURES",
        "spot": "SPOT INDICES",
        "stocks": "NSE STOCKS",
        "fii_dii": "FII/DII DATA",
    }
    
    for cat, label in category_labels.items():
        if cat in categories:
            print(f"\n{label}")
            print("-" * 40)
            for name, info in sorted(categories[cat]):
                print(f"  • {name:30s} [{info['display_name']}]")
    
    print("\n" + "=" * 60)
    print(f"Total datasets: {len(catalog)}")
    print("=" * 60 + "\n")


def load_ohlcv(
    dataset_name: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """
    Load OHLCV data from a dataset.
    
    Args:
        dataset_name: Name of the dataset (from catalog)
        start_date: Filter start date (YYYY-MM-DD)
        end_date: Filter end date (YYYY-MM-DD)
        limit: Limit number of rows (for testing)
    
    Returns:
        DataFrame with normalized columns: datetime, open, high, low, close, volume, oi
    """
    catalog = get_dataset_catalog()
    
    if dataset_name not in catalog:
        available = list(catalog.keys())
        raise ValueError(f"Dataset '{dataset_name}' not found. Available: {available[:10]}...")
    
    info = catalog[dataset_name]
    file_path = info["path"]
    category = info["category"]
    
    print(f"Loading {dataset_name} from {category}...")
    
    # Load based on category (liek on different formats)
    if category == "future":
        # Future format: date,time,open,high,low,close,volume,oi
        df = pd.read_csv(file_path, nrows=limit)
        # Parse date and time into datetime
        df["datetime"] = pd.to_datetime(
            df["date"] + " " + df["time"],
            format="%d/%m/%y %H:%M:%S",
            errors="coerce"
        )
        df = df[["datetime", "open", "high", "low", "close", "volume", "oi"]]
        
    elif category == "spot":
        # Spot format: datetime (with timezone),open,high,low,close,volume,oi
        df = pd.read_csv(file_path, nrows=limit)
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        # Remove timezone info for consistency
        if df["datetime"].dt.tz is not None:
            df["datetime"] = df["datetime"].dt.tz_localize(None)
        df = df[["datetime", "open", "high", "low", "close", "volume", "oi"]]
        
    elif category == "stocks":
        # Stocks format: datetime,date,time,open,high,low,close,volume,oi
        df = pd.read_csv(file_path, nrows=limit)
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df[["datetime", "open", "high", "low", "close", "volume", "oi"]]
        
    else:
        raise ValueError(f"Unsupported category: {category}")
    
    # Drop rows with invalid datetime
    df = df.dropna(subset=["datetime"])
    
    # Apply date filters
    if start_date:
        start = pd.to_datetime(start_date)
        df = df[df["datetime"] >= start]
    
    if end_date:
        end = pd.to_datetime(end_date)
        df = df[df["datetime"] <= end]
    
    # Sort by datetime
    df = df.sort_values("datetime").reset_index(drop=True)
    
    print(f"  Loaded {len(df):,} records from {df['datetime'].min()} to {df['datetime'].max()}")
    
    return df


def load_fii_dii(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    client_type: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load FII/DII participant data.
    
    Args:
        start_date: Filter start date (YYYY-MM-DD)
        end_date: Filter end date (YYYY-MM-DD)
        client_type: Filter by client type (FII, DII, Client, Pro, TOTAL)
    
    Returns:
        DataFrame with FII/DII data
    """
    file_path = DATASET_CATEGORIES["fii_dii"]
    
    if not file_path.exists():
        raise FileNotFoundError(f"FII/DII data not found at {file_path}")
    
    print("Loading FII/DII participant data...")
    
    # Read CSV
    df = pd.read_csv(file_path)
    
    # Parse date (format: DD/MM/YY)
    df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%y", errors="coerce")
    
    # Drop rows with invalid dates
    df = df.dropna(subset=["Date"])
    
    # Apply filters
    if start_date:
        start = pd.to_datetime(start_date)
        df = df[df["Date"] >= start]
    
    if end_date:
        end = pd.to_datetime(end_date)
        df = df[df["Date"] <= end]
    
    if client_type:
        df = df[df["Client_Type"] == client_type]
    
    # Sort by date
    df = df.sort_values("Date").reset_index(drop=True)
    
    print(f"  Loaded {len(df):,} records from {df['Date'].min()} to {df['Date'].max()}")
    
    return df


def convert_to_binary(df: pd.DataFrame, symbol_id: int, output_file: str) -> None:
    """
    Convert OHLCV DataFrame to binary format for C++ engine.
    
    Binary format per record (TickRecord):
    - timestamp: uint64 (nanoseconds since epoch)
    - symbol_id: uint64
    - price: double (close price used)
    - volume: double
    - flags: uint8 (1 = trade)
    - pad: 7 bytes
    
    Total: 41 bytes per record (with padding)
    Format string: <QQddB7x
    """
    print(f"Converting {len(df):,} records to binary format...")
    
    # Ensure output directory exists
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, "wb") as f:
        for _, row in df.iterrows():
            # Convert timestamp to nanoseconds
            ts = int(row["datetime"].timestamp() * 1e9)
            
            price = float(row["close"])
            volume = float(row["volume"])
            flags = 1  # Trade flag
            
            # Pack binary data
            packed = struct.pack("<QQddB7x", ts, symbol_id, price, volume, flags)
            f.write(packed)
    
    file_size = output_path.stat().st_size
    print(f"  ✓ Saved to {output_file} ({file_size:,} bytes)")


def get_dataset_info(dataset_name: str) -> Dict:
    """Get detailed info about a dataset including row count and date range."""
    catalog = get_dataset_catalog()
    
    if dataset_name not in catalog:
        raise ValueError(f"Dataset '{dataset_name}' not found")
    
    info = catalog[dataset_name].copy()
    
    # Load sample to get metadata
    try:
        if info["category"] == "fii_dii":
            df = load_fii_dii()
            info["rows"] = len(df)
            info["start_date"] = str(df["Date"].min())
            info["end_date"] = str(df["Date"].max())
            info["columns"] = list(df.columns)
        else:
            df = load_ohlcv(dataset_name, limit=None)
            info["rows"] = len(df)
            info["start_date"] = str(df["datetime"].min())
            info["end_date"] = str(df["datetime"].max())
            info["columns"] = list(df.columns)
    except Exception as e:
        info["error"] = str(e)
    
    return info


def main():
    parser = argparse.ArgumentParser(
        description="Felix Backtester - Dataset Loader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python load_datasets.py --list
  python load_datasets.py --dataset nifty50_spot --output data/processed/nifty50.bin
  python load_datasets.py --dataset reliance --start 2023-01-01 --end 2023-12-31
  python load_datasets.py --info reliance
        """
    )
    
    parser.add_argument("--list", "-l", action="store_true", help="List all available datasets")
    parser.add_argument("--dataset", "-d", type=str, help="Dataset name to load")
    parser.add_argument("--output", "-o", type=str, help="Output binary file path")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--symbol-id", type=int, default=1, help="Symbol ID for binary format")
    parser.add_argument("--info", type=str, help="Show detailed info for a dataset")
    parser.add_argument("--preview", type=int, help="Preview N rows of data")
    
    args = parser.parse_args()
    
    if args.list:
        list_datasets()
        return
    
    if args.info:
        info = get_dataset_info(args.info)
        print(f"\n Dataset: {args.info}")
        print("-" * 40)
        for key, value in info.items():
            print(f"  {key}: {value}")
        print()
        return
    
    if args.dataset:
        # Load the dataset
        df = load_ohlcv(
            args.dataset,
            start_date=args.start,
            end_date=args.end,
            limit=args.preview,
        )
        
        if args.preview:
            print(f"\n Preview ({args.preview} rows):")
            print(df.head(args.preview).to_string())
            print()
        
        if args.output:
            convert_to_binary(df, args.symbol_id, args.output)
            print(f"\n Dataset ready for backtesting: {args.output}")
        elif not args.preview:
            # Default output
            output_file = str(OUTPUT_DIR / f"{args.dataset}.bin")
            convert_to_binary(df, args.symbol_id, output_file)
            print(f"\n Dataset ready for backtesting: {output_file}")
        
        return
    
    # Default: show help
    parser.print_help()


if __name__ == "__main__":
    main()