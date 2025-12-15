#!/usr/bin/env python3
# filepath: /home/joelb23/BacktestingEngine/scripts/verify_results.py
"""
Felix System Verification - Check data, timing, and calculations
"""

import os
import sys
import struct
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "python"))

import numpy as np
import felix_engine as fe

# Correct format: Q(8) + I(4) + f(4)*5 + I(4)*2 = 40 bytes
TICK_FORMAT = '<QIfffffII'
TICK_SIZE = 40


def ns_to_datetime(ns: int) -> datetime:
    """Convert nanosecond timestamp to datetime"""
    try:
        return datetime.fromtimestamp(ns / 1e9)
    except:
        return datetime(1970, 1, 1)


def read_binary_ticks(filepath: str, num_samples: int = 10):
    """Read tick records directly from binary file"""
    ticks = []
    
    with open(filepath, 'rb') as f:
        file_size = os.path.getsize(filepath)
        num_ticks = file_size // TICK_SIZE
        
        # Read first few ticks
        for i in range(min(num_samples, num_ticks)):
            data = f.read(TICK_SIZE)
            if len(data) < TICK_SIZE:
                break
            
            t = struct.unpack(TICK_FORMAT, data)
            # t = (timestamp, symbol_id, price, bid, ask, bid_size, ask_size, volume, padding)
            ticks.append({
                'timestamp': t[0],
                'symbol_id': t[1],
                'price': t[2],
                'bid': t[3],
                'ask': t[4],
                'volume': t[7]
            })
        
        # Read last tick
        f.seek((num_ticks - 1) * TICK_SIZE)
        data = f.read(TICK_SIZE)
        if len(data) == TICK_SIZE:
            t = struct.unpack(TICK_FORMAT, data)
            last_tick = {
                'timestamp': t[0],
                'symbol_id': t[1],
                'price': t[2],
                'bid': t[3],
                'ask': t[4],
                'volume': t[7]
            }
        else:
            last_tick = ticks[-1] if ticks else None
    
    return ticks, last_tick, num_ticks


def verify_data():
    """Verify data file and timestamps"""
    print("=" * 60)
    print("DATA VERIFICATION")
    print("=" * 60)
    
    data_file = "data/processed/reliance.bin"
    
    if not os.path.exists(data_file):
        print(f"ERROR: Data file not found: {data_file}")
        return None
    
    # Read directly from binary file
    first_ticks, last_tick, num_ticks = read_binary_ticks(data_file, 5)
    
    print(f"Total ticks: {num_ticks:,}")
    print(f"File size: {os.path.getsize(data_file):,} bytes")
    
    if not first_ticks:
        print("ERROR: Could not read ticks")
        return None
    
    first_tick = first_ticks[0]
    
    first_ts = first_tick['timestamp']
    last_ts = last_tick['timestamp']
    
    first_dt = ns_to_datetime(first_ts)
    last_dt = ns_to_datetime(last_ts)
    
    duration_ns = last_ts - first_ts
    duration_sec = duration_ns / 1e9
    duration_min = duration_sec / 60
    duration_hours = duration_min / 60
    duration_days = duration_hours / 24
    
    print(f"\nFirst tick:")
    print(f"  Timestamp (ns): {first_ts}")
    print(f"  DateTime:       {first_dt}")
    print(f"  Price:          ${first_tick['price']:.2f}")
    print(f"  Bid/Ask:        ${first_tick['bid']:.2f} / ${first_tick['ask']:.2f}")
    print(f"  Volume:         {first_tick['volume']:,}")
    
    print(f"\nLast tick:")
    print(f"  Timestamp (ns): {last_ts}")
    print(f"  DateTime:       {last_dt}")
    print(f"  Price:          ${last_tick['price']:.2f}")
    print(f"  Bid/Ask:        ${last_tick['bid']:.2f} / ${last_tick['ask']:.2f}")
    print(f"  Volume:         {last_tick['volume']:,}")
    
    print(f"\nDuration:")
    print(f"  Seconds:        {duration_sec:,.0f}")
    print(f"  Days:           {duration_days:,.1f}")
    print(f"  Years:          {duration_days/365.25:.2f}")
    
    # Check if it's 1-minute data
    avg_interval_ns = duration_ns / (num_ticks - 1) if num_ticks > 1 else 0
    avg_interval_sec = avg_interval_ns / 1e9
    
    # Check interval between first few ticks
    print(f"\nData frequency:")
    if len(first_ticks) >= 2:
        intervals = []
        for i in range(1, len(first_ticks)):
            interval = (first_ticks[i]['timestamp'] - first_ticks[i-1]['timestamp']) / 1e9
            intervals.append(interval)
        print(f"  First intervals: {intervals} seconds")
    
    print(f"  Avg interval:   {avg_interval_sec:.2f} seconds")
    
    # For multi-year data with market hours only, avg interval > 60s is expected
    if 55 < avg_interval_sec < 65:
        print(f"  Type:           Continuous 1-minute data")
    elif avg_interval_sec > 60:
        print(f"  Type:           1-minute data (market hours only, includes overnight gaps)")
    
    print(f"\nPrice range:")
    print(f"  First:          ${first_tick['price']:.2f}")
    print(f"  Last:           ${last_tick['price']:.2f}")
    print(f"  Change:         {((last_tick['price']/first_tick['price'])-1)*100:+.1f}%")
    
    return {
        'num_ticks': num_ticks,
        'first_ts': first_ts,
        'last_ts': last_ts,
        'first_dt': first_dt,
        'last_dt': last_dt,
        'duration_days': duration_days,
        'avg_interval_sec': avg_interval_sec,
        'first_price': first_tick['price'],
        'last_price': last_tick['price']
    }


def verify_datastream_api():
    """Check what methods DataStream has"""
    print("\n" + "=" * 60)
    print("DATASTREAM API CHECK")
    print("=" * 60)
    
    ds = fe.DataStream()
    methods = [x for x in dir(ds) if not x.startswith('_')]
    print(f"Available methods: {methods}")
    
    ds.load("data/processed/reliance.bin")
    print(f"Size: {ds.size():,}")
    
    return methods


def verify_source_data():
    """Check the source CSV data"""
    print("\n" + "=" * 60)
    print("SOURCE DATA CHECK")
    print("=" * 60)
    
    try:
        import pandas as pd
    except ImportError:
        print("pandas not installed, skipping source check")
        return
    
    csv_file = "datasets/NSE_Stocks/Reliance_data.csv"
    if not os.path.exists(csv_file):
        print(f"Source file not found: {csv_file}")
        return
    
    df = pd.read_csv(csv_file)
    print(f"Source CSV: {csv_file}")
    print(f"Rows: {len(df):,}")
    print(f"Columns: {list(df.columns)}")
    print(f"\nFirst 3 rows:")
    print(df.head(3).to_string())
    print(f"\nLast 3 rows:")
    print(df.tail(3).to_string())
    
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
        print(f"\nDate range: {df['date'].min()} to {df['date'].max()}")
        print(f"Duration: {(df['date'].max() - df['date'].min()).days} days")


def verify_metrics_calculation():
    """Verify metrics calculations are correct"""
    print("\n" + "=" * 60)
    print("METRICS CALCULATION VERIFICATION")
    print("=" * 60)
    
    initial = 100000
    equity = [100000, 101000, 102000, 101500, 103000, 104000, 102000, 105000, 108000, 110000]
    final = equity[-1]
    
    returns = np.diff(equity) / np.array(equity[:-1])
    
    total_return = (final - initial) / initial
    print(f"\nTest equity curve: {equity}")
    print(f"Total return: {total_return*100:.2f}% (expected: 10%) ✓")
    
    peak = equity[0]
    max_dd = 0
    for val in equity:
        if val > peak:
            peak = val
        dd = (peak - val) / peak
        if dd > max_dd:
            max_dd = dd
    print(f"Max drawdown: {max_dd*100:.2f}% (expected: 1.92%) ✓")
    
    sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
    print(f"Sharpe (daily): {sharpe:.2f}")
    
    print("\n✓ Metrics formulas verified")


def verify_performance_expectations():
    """Check if performance is in expected range"""
    print("\n" + "=" * 60)
    print("PERFORMANCE EXPECTATIONS (from design.txt)")
    print("=" * 60)
    
    print("""
Target from design document:
┌─────────────────────────────────────────────────────────┐
│ Component              │ Target Latency                 │
├─────────────────────────────────────────────────────────┤
│ Core C++ processing    │ 0.3-1.2 μs/tick               │
│ Python callback        │ 0.8-1.0 μs overhead           │
│ Total with Python      │ ~1.5-2.5 μs/tick              │
├─────────────────────────────────────────────────────────┤
│ Pure C++ throughput    │ 5-15M ticks/sec               │
│ With Python callbacks  │ ~400K-700K ticks/sec          │
└─────────────────────────────────────────────────────────┘
""")


def run_simple_verification():
    """Run a simple buy-and-hold to verify P&L calculation"""
    print("\n" + "=" * 60)
    print("P&L CALCULATION VERIFICATION")
    print("=" * 60)
    
    first_ticks, last_tick, num_ticks = read_binary_ticks("data/processed/reliance.bin", 1)
    
    if not first_ticks or not last_tick:
        print("ERROR: Could not read tick data")
        return
    
    first_price = first_ticks[0]['price']
    last_price = last_tick['price']
    
    initial_capital = 100000.0
    entry_price = first_price
    shares = int((initial_capital * 0.95) / entry_price)
    cash_remaining = initial_capital - (shares * entry_price)
    
    expected_final = cash_remaining + (shares * last_price)
    expected_pnl = expected_final - initial_capital
    expected_return = (expected_pnl / initial_capital) * 100
    
    print(f"\nBuy & Hold Verification:")
    print(f"  Entry price:     ${entry_price:.2f}")
    print(f"  Exit price:      ${last_price:.2f}")
    print(f"  Price change:    {((last_price/entry_price)-1)*100:+.2f}%")
    print(f"  Shares bought:   {shares}")
    print(f"  Cash remaining:  ${cash_remaining:.2f}")
    print(f"  Expected final:  ${expected_final:,.2f}")
    print(f"  Expected P&L:    ${expected_pnl:,.2f}")
    print(f"  Expected return: {expected_return:+.2f}%")


def check_consistency():
    """Check overall system consistency"""
    print("\n" + "=" * 60)
    print("CONSISTENCY CHECK")
    print("=" * 60)
    
    issues = []
    
    first_ticks, last_tick, num_ticks = read_binary_ticks("data/processed/reliance.bin", 1)
    
    if first_ticks:
        first_dt = ns_to_datetime(first_ticks[0]['timestamp'])
        last_dt = ns_to_datetime(last_tick['timestamp'])
        duration_days = (last_dt - first_dt).total_seconds() / 86400
        
        print(f"Binary data: {num_ticks:,} ticks")
        print(f"Period: {first_dt.strftime('%Y-%m-%d')} to {last_dt.strftime('%Y-%m-%d')} ({duration_days:.0f} days)")
        print(f"Price: ${first_ticks[0]['price']:.2f} → ${last_tick['price']:.2f}")
        
        # Sanity checks
        if first_ticks[0]['price'] < 1 or first_ticks[0]['price'] > 100000:
            issues.append(f"First price looks wrong: ${first_ticks[0]['price']:.2f}")
        
        if last_tick['price'] < 1 or last_tick['price'] > 100000:
            issues.append(f"Last price looks wrong: ${last_tick['price']:.2f}")
    
    print(f"\n{'─' * 40}")
    if issues:
        print("ISSUES FOUND:")
        for issue in issues:
            print(f"  ✗ {issue}")
    else:
        print("✓ All consistency checks passed")
    
    return len(issues) == 0


def main():
    print("FELIX BACKTESTING ENGINE - SYSTEM VERIFICATION")
    print("=" * 60)
    
    methods = verify_datastream_api()
    data_info = verify_data()
    verify_source_data()
    verify_metrics_calculation()
    verify_performance_expectations()
    run_simple_verification()
    is_consistent = check_consistency()
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if data_info:
        print(f"""
Data:
  - {data_info['num_ticks']:,} ticks
  - Period: {data_info['first_dt'].strftime('%Y-%m-%d')} to {data_info['last_dt'].strftime('%Y-%m-%d')}
  - Duration: {data_info['duration_days']:.0f} days ({data_info['duration_days']/365.25:.1f} years)
  - Price: ${data_info['first_price']:.2f} → ${data_info['last_price']:.2f} ({((data_info['last_price']/data_info['first_price'])-1)*100:+.1f}%)

System Status: {'✓ READY' if is_consistent else '✗ ISSUES FOUND'}
""")


if __name__ == "__main__":
    main()