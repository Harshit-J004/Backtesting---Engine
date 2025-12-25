import pandas as pd
import os

def check_results():
    file_path = 'dashboard_data/basket_summary.csv'
    
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        return

    print(f"Checking Results from: {file_path}")
    print("=" * 50)
    
    try:
        df = pd.read_csv(file_path)
        
        # 1. TOTALS
        winners = df[df['net_pnl'] > 0]
        losers = df[df['net_pnl'] <= 0]
        
        win_sum = winners['net_pnl'].sum()
        loss_sum = losers['net_pnl'].sum()
        net_total = df['net_pnl'].sum()
        
        win_count = len(winners)
        loss_count = len(losers)
        total_count = len(df)
        
        print(f"Winning Trades: {win_count:5d}  |  Total: ${win_sum:,.2f}")
        print(f"Losing Trades:  {loss_count:5d}  |  Total: ${loss_sum:,.2f}")
        print("-" * 50)
        print(f"NET P&L:        {total_count:5d}  |  Value: ${net_total:,.2f}")
        print("=" * 50)

        # 2. MONTHLY BREAKDOWN
        print("\nMonthly Returns (Dynamic Calculation):")
        print("-" * 35)
        
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            # Resample to Monthly End
            monthly_pnl = df.set_index('date').resample('ME')['net_pnl'].sum()
            
            # Print all non-zero months
            for date, val in monthly_pnl.items():
                if val != 0:
                    month_str = date.strftime('%Y-%m')
                    print(f"{month_str}: ${val:,.2f}")
        else:
            print("Error: 'date' column not found for monthly breakdown.")
            
        print("-" * 35)
            
    except Exception as e:
        print(f"Error reading CSV: {e}")

if __name__ == "__main__":
    check_results()
