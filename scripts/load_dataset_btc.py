#!/usr/bin/env python3
"""
BTC/USDT Data Loader - Converts Binance 1-minute OHLCV CSVs to binary TickRecord format.
"""

import os
import sys
import struct
import argparse
import pandas as pd
from pathlib import Path
from typing import Optional
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
BTC_DATA_DIR = PROJECT_ROOT / "datasets" / "BTCUSDT_1m_data"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"

# Binary format: Q(8) + I(4) + f(4)*5 + I(4)*2 = 40 bytes
PACK_FORMAT = '<QIfffffII'
RECORD_SIZE = struct.calcsize(PACK_FORMAT)


def load_btc_csv(filepath: Path) -> pd.DataFrame:
    """Load a single BTC CSV file."""
    print(f"  Loading {filepath.name}...")
    
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.lower().str.strip()
    
    # Use open_time (milliseconds) as timestamp
    if 'open_time' in df.columns:
        df['datetime'] = pd.to_datetime(df['open_time'], unit='ms')
    elif 'timestamp' in df.columns:
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    else:
        raise ValueError(f"No timestamp column found in {filepath}")
    
    # Ensure required columns exist
    required = ['open', 'high', 'low', 'close', 'volume']
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing column '{col}' in {filepath}")
    
    print(f"    → {len(df):,} records from {df['datetime'].min()} to {df['datetime'].max()}")
    return df


def load_all_btc_data(start_year: Optional[int] = None, 
                       end_year: Optional[int] = None) -> pd.DataFrame:
    """Load and concatenate all BTC CSV files."""
    
    if not BTC_DATA_DIR.exists():
        raise FileNotFoundError(f"BTC data directory not found: {BTC_DATA_DIR}")
    
    csv_files = sorted(BTC_DATA_DIR.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {BTC_DATA_DIR}")
    
    print(f"Found {len(csv_files)} BTC CSV files")
    
    dfs = []
    for csv_file in csv_files:
        # Extract year from filename (e.g., BTC_USDT_1m_2019.csv → 2019)
        year = None
        for part in csv_file.stem.split('_'):
            if part.isdigit() and len(part) == 4:
                year = int(part)
                break
        
        # Filter by year if specified
        if start_year and year and year < start_year:
            continue
        if end_year and year and year > end_year:
            continue
        
        df = load_btc_csv(csv_file)
        dfs.append(df)
    
    if not dfs:
        raise ValueError("No data loaded after filtering")
    
    # Concatenate and sort
    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.sort_values('datetime').reset_index(drop=True)
    
    # Remove duplicates based on timestamp
    combined = combined.drop_duplicates(subset=['datetime'], keep='first')
    
    print(f"\nTotal: {len(combined):,} records")
    print(f"Date range: {combined['datetime'].min()} to {combined['datetime'].max()}")
    
    return combined

def convert_to_binary(df: pd.DataFrame, symbol_id: int, output_file: str) -> None:
    """Convert DataFrame to binary TickRecord format."""
    
    print(f"\nConverting {len(df):,} records to binary...")
    print(f"Format: {PACK_FORMAT}, Record size: {RECORD_SIZE} bytes")
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Validate datetime range
    valid_start = pd.Timestamp('2015-01-01')
    valid_end = pd.Timestamp('2030-01-01')
    
    df = df[(df['datetime'] >= valid_start) & (df['datetime'] <= valid_end)]
    print(f"After filtering invalid dates: {len(df):,} records")
    print(f"Date range: {df['datetime'].min()} to {df['datetime'].max()}")
    
    records_written = 0
    with open(output_file, "wb") as f:
        for idx, row in df.iterrows():
            # Timestamp: datetime → nanoseconds
            ts_ns = int(row['datetime'].timestamp() * 1e9)
            
            # Skip invalid timestamps
            if ts_ns <= 0:
                continue
            
            # Price: use close price
            price = float(row['close'])
            
            # Bid/Ask: approximate from close (BTC typically has tight spread)
            spread = price * 0.0001  # 0.01% spread approximation
            bid = price - spread
            ask = price + spread
            
            # Volume: use BTC volume, convert to integer (multiply by 1000 for precision)
            vol = int(float(row['volume']) * 1000)  # Store as milli-BTC for integer precision
            
            record = struct.pack(
                PACK_FORMAT,
                ts_ns,              # uint64: timestamp in nanoseconds
                symbol_id,          # uint32: symbol ID
                price,              # float: price (close)
                bid,                # float: bid price
                ask,                # float: ask price
                100.0,              # float: bid_size (placeholder)
                100.0,              # float: ask_size (placeholder)
                vol,                # uint32: volume
                0                   # uint32: flags
            )
            f.write(record)
            
            # Progress indicator
            records_written += 1
            if (idx + 1) % 500000 == 0:
                print(f"  Written {idx + 1:,} records...")
    
    file_size = output_path.stat().st_size
    expected_size = len(df) * RECORD_SIZE
    
    print(f"\n✓ Saved {file_size // RECORD_SIZE:,} records to {output_file}")
    print(f"  File size: {file_size:,} bytes ({file_size / 1e6:.1f} MB)")
    
    if file_size != expected_size:
        print(f"  ⚠ Warning: Expected {expected_size:,} bytes, got {file_size:,}")


def verify_binary(filepath: str, num_records: int = 5) -> None:
    """Verify binary file by reading first few records."""
    
    print(f"\nVerifying {filepath}...")
    
    with open(filepath, 'rb') as f:
        for i in range(num_records):
            data = f.read(RECORD_SIZE)
            if not data:
                break
            
            ts, sym, price, bid, ask, bid_sz, ask_sz, vol, flags = struct.unpack(PACK_FORMAT, data)
            dt = pd.Timestamp(ts, unit='ns')
            
            print(f"  [{i+1}] {dt} | price=${price:.2f} | bid=${bid:.2f} | ask=${ask:.2f} | vol={vol}")


def main():
    parser = argparse.ArgumentParser(description="BTC/USDT Data Loader for Felix Backtester")
    parser.add_argument("--output", "-o", type=str, 
                        default="data/processed/btcusdt.bin",
                        help="Output binary file path")
    parser.add_argument("--start-year", type=int, help="Start year (e.g., 2020)")
    parser.add_argument("--end-year", type=int, help="End year (e.g., 2023)")
    parser.add_argument("--symbol-id", type=int, default=2, 
                        help="Symbol ID for BTC (default: 2)")
    parser.add_argument("--verify", action="store_true", 
                        help="Verify output file after creation")
    parser.add_argument("--preview", type=int, 
                        help="Preview N rows without converting")
    args = parser.parse_args()
    
    # Validate record size
    assert RECORD_SIZE == 40, f"RECORD_SIZE should be 40, got {RECORD_SIZE}"
    
    print("=" * 60)
    print("FELIX BACKTESTER - BTC/USDT DATA LOADER")
    print("=" * 60)
    
    # Load data
    df = load_all_btc_data(args.start_year, args.end_year)
    
    if args.preview:
        print(f"\nPreview (first {args.preview} rows):")
        print(df[['datetime', 'open', 'high', 'low', 'close', 'volume']].head(args.preview).to_string())
        return
    
    # Convert to binary
    convert_to_binary(df, args.symbol_id, args.output)
    
    # Verify if requested
    if args.verify:
        verify_binary(args.output)
    
    print("\n" + "=" * 60)
    print(f"✓ Ready to use: {args.output}")
    print("=" * 60)


if __name__ == "__main__":
    main()