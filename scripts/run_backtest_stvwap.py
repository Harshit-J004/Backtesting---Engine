import sys
import os
from datetime import datetime

# Setup paths
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "python"))

import felix_engine as fe
from felix.strategy.base import Strategy
from felix.analytics.metrics import BacktestResults


class VWAPStrategy(Strategy):
    """
    VWAP Mean Reversion Strategy.
    Entry: Price crosses below VWAP (mean reversion)
    Exit: 3% target or 2% stop-loss
    """
    
    def __init__(self, engine: fe.MatchingEngine, portfolio: fe.Portfolio, risk_engine: fe.RiskEngine):
        self.engine = engine
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        
        # VWAP tracking
        self.cumulative_pv = 0.0
        self.cumulative_vol = 0.0
        self.vwap = None
        self.prev_vwap = None
        self.prev_price = None
        
        # Position tracking
        self.position = 0
        self.entry_price = 0.0
        self.stop_price = 0.0
        self.target_price = 0.0
        
        # Analytics
        self.equity_curve = []
        self.trades = []
        self.initial_cash = portfolio.cash()
        self.peak_equity = portfolio.cash()
        self.risk_halted = False
        
    def on_start(self):
        print("="*60)
        print("VWAP Strategy Started")
        print("Stop Loss: 2.0%")
        print("Target: 3.0%")
        print("="*60)
        self.equity_curve.append(self.portfolio.cash())
    
    def on_tick(self, tick):
        # Update portfolio mark-to-market
        self.portfolio.update_prices(tick.symbol_id, tick.price)
        
        # Record equity
        equity = self.portfolio.cash()
        if self.position != 0:
            equity += self.position * tick.price
        self.equity_curve.append(equity)
        
        # Update peak equity
        if equity > self.peak_equity:
            self.peak_equity = equity
        
        price = tick.price
        volume = tick.volume
        
        # Update VWAP
        self.cumulative_pv += price * volume
        self.cumulative_vol += volume
        
        if self.cumulative_vol > 0:
            self.vwap = self.cumulative_pv / self.cumulative_vol
        
        # Entry: Price crosses below VWAP (mean reversion)
        if (self.position == 0 and 
            self.prev_price is not None and 
            self.prev_vwap is not None):
            
            # Price was above VWAP, now below (mean reversion entry)
            if self.prev_price > self.prev_vwap and price < self.vwap:
                # Risk checks
                if self.risk_halted:
                    return
                
                if not self.risk_engine.check_drawdown(self.portfolio, self.peak_equity):
                    print(f"  [RISK] Halted - Max drawdown exceeded!")
                    self.risk_halted = True
                    return
                
                shares = 100
                self.position = shares
                self.entry_price = price
                self.stop_price = price * 0.98  # 2% stop
                self.target_price = price * 1.03  # 3% target
                
                print(f"  [ENTRY] BUY {shares} @ ${price:.2f} | VWAP=${self.vwap:.2f} | Stop=${self.stop_price:.2f} | Target=${self.target_price:.2f}")
                
                self.trades.append({
                    'datetime': datetime.fromtimestamp(tick.timestamp / 1e9).strftime('%Y-%m-%d %H:%M:%S'),
                    'side': 'BUY',
                    'price': round(price, 2),
                    'shares': shares,
                    'pnl': 0.0,
                })
        
        # Exit: Stop-loss or target
        if self.position > 0:
            exit_reason = None
            exit_price = None
            
            if price <= self.stop_price:
                exit_reason = "STOP_LOSS"
                exit_price = self.stop_price
            elif price >= self.target_price:
                exit_reason = "TARGET"
                exit_price = self.target_price
            
            if exit_reason:
                pnl = (exit_price - self.entry_price) * self.position
                print(f"  [EXIT] SELL {self.position} @ ${exit_price:.2f} | {exit_reason} | P&L: ${pnl:+.2f}")
                
                self.trades.append({
                    'datetime': datetime.fromtimestamp(tick.timestamp / 1e9).strftime('%Y-%m-%d %H:%M:%S'),
                    'side': 'SELL',
                    'price': round(exit_price, 2),
                    'shares': self.position,
                    'pnl': round(pnl, 2),
                })
                
                self.position = 0
        
        # Update previous values
        self.prev_price = price
        self.prev_vwap = self.vwap
    
    def on_fill(self, fill):
        pass
    
    def on_bar(self, bar):
        pass
    
    def on_end(self):
        print("\n" + "="*60)
        print("VWAP Strategy Complete")
        print("="*60)
        
        results = BacktestResults(
            equity_curve=self.equity_curve,
            trades=self.trades,
            initial_capital=self.initial_cash
        )
        results.print_summary()
        
        results.export_json("results/vwap_backtest_results.json")
        results.export_trades_csv("results/vwap_trades.csv")


def main():
    data_file = "data/processed/market_data.bin"
    
    if not os.path.exists(data_file):
        print(f"Error: {data_file} not found.")
        print("Run: python scripts/preprocess_data.py --symbol AAPL --start 2025-01-01 --end 2025-06-01")
        return
    
    os.makedirs("results", exist_ok=True)
    
    stream = fe.DataStream()
    stream.load(data_file)
    print(f"Loaded {data_file}")
    
    slippage = fe.SlippageConfig()
    slippage.fixed_bps = 5.0
    
    engine = fe.MatchingEngine(slippage)
    portfolio = fe.Portfolio(100000.0)
    
    risk_limits = fe.RiskLimits()
    risk_limits.max_drawdown = 0.20
    risk_limits.max_position_size = 1000
    risk_limits.max_order_size = 500
    risk_engine = fe.RiskEngine(risk_limits)
    
    print(f"Initial Capital: $100,000")
    print(f"Risk Limits: Max DD={risk_limits.max_drawdown*100}%, Max Position={risk_limits.max_position_size}")
    
    strategy = VWAPStrategy(engine, portfolio, risk_engine)
    
    strategy.on_start()
    
    loop = fe.EventLoop()
    loop.run(stream, strategy)
    
    strategy.on_end()


if __name__ == "__main__":
    main()