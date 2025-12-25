import csv
import os
import pandas as pd
from datetime import datetime, timedelta

class DashboardExporter:
    def __init__(self, output_dir="dashboard_data"):
        self.output_dir = output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
    def export(self, equity_curve, trades, initial_capital):
        """
        Main export function called by strategy runner
        """
        print(f"Exporting dashboard data to {self.output_dir}...")
        self._export_equity_curve(equity_curve, initial_capital)
        self._export_baskets_and_trades(trades)
        print("Export Complete.")

    def _export_equity_curve(self, equity_curve, initial_capital):
        data = []
        start_date = datetime(2021, 1, 1)
        
        for idx, eq in enumerate(equity_curve):
            # One point per day assumption if size matches approx duration
            date_str = (start_date + timedelta(days=idx)).strftime('%Y-%m-%d')
            data.append({
                'date': date_str,
                'total_equity': f"{eq:.2f}",
                'capital': f"{initial_capital:.2f}"
            })
            
        df = pd.DataFrame(data)
        df.to_csv(os.path.join(self.output_dir, "equity_curve.csv"), index=False)

    def _export_baskets_and_trades(self, trades):
        basket_data = []
        trade_log = []
        
        last_entry_time = {} # Map bucket/strategy to timestamp
        
        # Sort by time
        sorted_trades = sorted(trades, key=lambda x: x['timestamp'])

        basket_id_counter = 1

        for t in sorted_trades:
            # Convert timestamp to date
            dt = datetime.utcfromtimestamp(t['timestamp'] / 1e9) # ns to seconds
            date_str = dt.strftime('%Y-%m-%d')
            strat = t.get('strategy', 'Unknown')
            
            if t['type'] == 'entry':
                last_entry_time[strat] = t['timestamp']
            
            # Use variables here since they are definitely assigned in this iteration
            basket_id = f"{strat}-{date_str}-{basket_id_counter}"
            
            # Add to trade log
            trade_log.append({
                'basket_id': basket_id,
                'trade_num': str(len(trade_log) + 1),
                'lot_size': str(abs(t['size'])),
                'slippage_pips': "0.5"
            })
            
            # Add to basket summary (only on exits)
            if t['type'] == 'exit':
                pnl = t.get('pnl', 0)
                
                # Calculate Duration
                entry_ts = last_entry_time.get(strat, t['timestamp'])
                duration_ns = t['timestamp'] - entry_ts
                duration_sec = max(0.001, duration_ns / 1e9) # Keep as float seconds
                
                basket_data.append({
                    'date': date_str,
                    'net_pnl': f"{pnl:.2f}",
                    'duration_seconds': f"{duration_sec:.3f}"
                })
                # Increment basket counter only after a closed cycle
                basket_id_counter += 1

        # Write Basket Summary
        if basket_data:
            pd.DataFrame(basket_data).to_csv(os.path.join(self.output_dir, "basket_summary.csv"), index=False)
        else:
             # Create empty with headers
             pd.DataFrame(columns=['date', 'net_pnl', 'duration_seconds']).to_csv(os.path.join(self.output_dir, "basket_summary.csv"), index=False)

        # Write Trade Log
        if trade_log:
            pd.DataFrame(trade_log).to_csv(os.path.join(self.output_dir, "trade_log.csv"), index=False)
        else:
             pd.DataFrame(columns=['basket_id', 'trade_num', 'lot_size', 'slippage_pips']).to_csv(os.path.join(self.output_dir, "trade_log.csv"), index=False)
