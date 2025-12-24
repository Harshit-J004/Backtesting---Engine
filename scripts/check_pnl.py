import pandas as pd
try:
    df = pd.read_csv('results/trades.csv')
    total_pnl = df['pnl'].sum()
    win_rate = (len(df[df['pnl'] > 0]) / len(df) * 100) if len(df) > 0 else 0
    total_trades = len(df)
    
    print(f"Total Trades: {total_trades}")
    print(f"Total PnL: {total_pnl:.2f}")
    print(f"Win Rate: {win_rate:.1f}%")
except Exception as e:
    print(f"Error: {e}")
