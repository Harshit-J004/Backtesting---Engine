import pandas as pd
import glob
import os

files = {
    "MA Crossover": "results/trades.csv",
    "Bollinger": "results/bollinger_trades.csv",
    "Momentum": "results/momentum_trades.csv"
}

print(f"{'STRATEGY':<20} | {'TRADES':<10} | {'WIN RATE':<10} | {'TOTAL PL':<15}")
print("-" * 65)

for name, filepath in files.items():
    if os.path.exists(filepath):
        try:
            df = pd.read_csv(filepath)
            total_trades = len(df)
            total_pnl = df['pnl'].sum()
            win_rate = (len(df[df['pnl'] > 0]) / len(df) * 100) if len(df) > 0 else 0
            
            print(f"{name:<20} | {total_trades:<10} | {win_rate:>8.1f}% | ${total_pnl:>12.2f}")
        except Exception as e:
            print(f"{name:<20} | ERROR READING FILE")
    else:
        print(f"{name:<20} | NO DATA FOUND")
