import sys
import os
from datetime import datetime
from pathlib import Path
# Setup paths
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# sys.path.insert(0, root_dir)
sys.path.insert(0, os.path.join(root_dir, "python"))
# sys.path.insert(0, str(Path(__file__).parent.parent))

# Adding compiled engine path relative to project root (which is in sys.path[1] or similar, but better explicit)
sys.path.append(os.path.join(project_root, "Release"))

import felix_engine as fe
from felix.strategy.base import Strategy
from felix.analytics.metrics import BacktestResults


class SampleStrategy(Strategy):
    """
    Sample Moving Average Crossover Strategy.
    Demonstrates: on_start, on_tick, on_fill, on_bar, on_end callbacks with risk checks.
    """
    
    def __init__(self, engine: fe.MatchingEngine, portfolio: fe.Portfolio, risk_engine: fe.RiskEngine):
        self.engine = engine
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        self.prices = []
        self.equity_curve = []
        self.trades = []
        self.position = 0
        self.entry_price = 0.0
        self.initial_cash = portfolio.cash()
        self.peak_equity = portfolio.cash()
        self.risk_halted = False
        
    def on_start(self):
        print("Backtest started.")
        self.equity_curve.append(self.portfolio.cash())
    
    def on_tick(self, tick):
        # Update portfolio mark-to-market
        self.portfolio.update_prices(tick.symbol_id, tick.price)
        
        # Record equity
        equity = self.portfolio.cash()
        if self.position != 0:
            equity += self.position * tick.price
        self.equity_curve.append(equity)
        
        # Store price for moving average
        self.prices.append(tick.price)
        
        # Need at least 5 prices for short MA
        if len(self.prices) < 5:
            return
        
        # Simple MA crossover: 3-period vs 5-period
        short_ma = sum(self.prices[-3:]) / 3
        long_ma = sum(self.prices[-5:]) / 5
        
        # Buy signal: short MA crosses above long MA
        if short_ma > long_ma and self.position == 0:
            # Risk check:- Is strategy halted?
            if self.risk_halted:
                return
            
            # Risk check: Drawdown limit
            if not self.risk_engine.check_drawdown(self.portfolio, self.peak_equity):
                print(f"  [RISK] Halted - Max drawdown exceeded!")
                self.risk_halted = True
                return
            
            shares = 100
            cost = shares * tick.price
            
            # Check if we have enough cash
            if self.portfolio.cash() < cost:
                print(f"  [RISK] Halted - Insufficient cash: ${self.portfolio.cash():.2f} < ${cost:.2f}")
                return

            self.position = shares
            self.entry_price = tick.price
            
            # Create Fill object to update portfolio
            fill = fe.Fill()
            fill.order_id = 999 # Dummy ID
            fill.symbol_id = tick.symbol_id
            fill.price = tick.price
            fill.volume = float(shares)
            fill.side = fe.Side.BUY
            
            self.portfolio.on_fill(fill)
            
            print(f"  [TRADE] BUY {shares} shares @ ${tick.price:.2f}")
            
            # Log trade with readable date
            self.trades.append({
                'datetime': datetime.fromtimestamp(tick.timestamp / 1e9).strftime('%Y-%m-%d %H:%M'),
                'side': 'BUY',
                'price': round(tick.price, 2),
                'shares': shares,
                'pnl': 0.0,
            })
            
        # Sell signal:- short MA crosses below long MA  
        elif short_ma < long_ma and self.position > 0:
            proceeds = self.position * tick.price
            pnl = (tick.price - self.entry_price) * self.position
            
            # Create Fill object to update portfolio
            fill = fe.Fill()
            fill.order_id = 999 
            fill.symbol_id = tick.symbol_id
            fill.price = tick.price
            fill.volume = float(self.position)
            fill.side = fe.Side.SELL
            
            self.portfolio.on_fill(fill)
            
            print(f"  [TRADE] SELL {self.position} shares @ ${tick.price:.2f} → P&L: ${pnl:+.2f}")
            
            self.trades.append({
                'datetime': datetime.fromtimestamp(tick.timestamp / 1e9).strftime('%Y-%m-%d %H:%M'),
                'side': 'SELL',
                'price': round(tick.price, 2),
                'shares': self.position,
                'pnl': round(pnl, 2),
            })
            
            self.position = 0
    
    def on_fill(self, fill):
        """Called when an order is filled by the matching engine."""
        print(f"  Fill: order_id={fill.order_id}, price=${fill.price:.2f}, volume={fill.volume}")
    
    def on_bar(self, bar):
        """Called on bar completion (e.g., 1-min, 5-min bars)."""
        pass  # Not used in tick-based strategy
    
    def on_end(self):
        print("Backtest complete.")
        
        # Compute and display results
        results = BacktestResults(
            equity_curve=self.equity_curve,
            trades=self.trades,
            initial_capital=self.initial_cash
        )
        results.print_summary()
        
        # Export
        results.export_json("results/backtest_results.json")
        results.export_trades_csv("results/trades.csv")


def main():
    data_file = "data/processed/reliance.bin"
    
    if not os.path.exists(data_file):
        print(f"Error: {data_file} not found.")
        print("Run: python scripts/load_datasets.py --dataset reliance --output data/processed/reliance.bin")
        return
    
    # Create results directory
    os.makedirs("results", exist_ok=True)
    
    # Initialize C++ components
    stream = fe.DataStream()
    stream.load(data_file)
    print(f"Loaded {data_file}")
    
    # Configure slippage (5 bps = 0.05%)
    slippage = fe.SlippageConfig()
    slippage.fixed_bps = 5.0
    
    engine = fe.MatchingEngine(slippage)
    portfolio = fe.Portfolio(100000.0)
    
    # Configure risk limits (20% max drawdown)
    risk_limits = fe.RiskLimits()
    risk_limits.max_drawdown = 0.20  # 20%
    risk_limits.max_position_size = 1000
    risk_limits.max_order_size = 500
    risk_engine = fe.RiskEngine(risk_limits)
    print(f"Risk limits: max_drawdown={risk_limits.max_drawdown*100}%, max_position={risk_limits.max_position_size}")
    
    # Create strategy with risk engine
    strategy = SampleStrategy(engine, portfolio, risk_engine)
    
    # Run backtest
    strategy.on_start()
    
    loop = fe.EventLoop()
    loop.run(stream, strategy)
    
    strategy.on_end()


if __name__ == "__main__":
    main()
