import sys
import os
from datetime import datetime
from collections import deque

# Setup paths
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "python"))

# Add compiled engine path relative to project root (which is in sys.path[1] or similar, but better explicit)
sys.path.append(os.path.join(project_root, "Release"))

import felix_engine as fe
from felix.strategy.base import Strategy
from felix.analytics.metrics import BacktestResults


class BollingerBandsStrategy(Strategy):
    """
    Bollinger Bands Mean Reversion Strategy.
    Entry: Price crosses below lower band (oversold)
    Exit: Price reaches middle band or 3% target or 2% stop-loss
    """
    
    def __init__(self, engine: fe.MatchingEngine, portfolio: fe.Portfolio, risk_engine: fe.RiskEngine):
        self.engine = engine
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        
        # Bollinger Bands parameters
        self.period = 20
        self.std_dev = 2.0
        self.prices = deque(maxlen=self.period)
        
        # Bands
        self.middle_band = None
        self.upper_band = None
        self.lower_band = None
        
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
        print("Bollinger Bands Strategy Started")
        print(f"Period: {self.period}, Std Dev: {self.std_dev}")
        print("Stop Loss: 2.0%, Target: 3.0%")
        print("="*60)
        self.equity_curve.append(self.portfolio.cash())
    
    def calculate_bands(self):
        """Calculate Bollinger Bands."""
        if len(self.prices) < self.period:
            return None, None, None
        
        prices_list = list(self.prices)
        mean = sum(prices_list) / len(prices_list)
        
        variance = sum((x - mean) ** 2 for x in prices_list) / len(prices_list)
        std = variance ** 0.5
        
        middle = mean
        upper = mean + (self.std_dev * std)
        lower = mean - (self.std_dev * std)
        
        return middle, upper, lower
    
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
        
        # Update price history
        self.prices.append(price)
        
        # Calculate Bollinger Bands
        prev_middle = self.middle_band
        prev_lower = self.lower_band
        
        self.middle_band, self.upper_band, self.lower_band = self.calculate_bands()
        
        # Need enough data
        if self.middle_band is None:
            return
        
        # Entry: Price crosses below lower band (oversold)
        if self.position == 0 and prev_lower is not None:
            if price < self.lower_band:
                # Risk checks
                if self.risk_halted:
                    return
                
                if not self.risk_engine.check_drawdown(self.portfolio, self.peak_equity):
                    print(f"  [RISK] Halted - Max drawdown exceeded!")
                    self.risk_halted = True
                    return
                
                shares = 100
                cost = shares * price
                
                 # Check if we have enough cash
                if self.portfolio.cash() < cost:
                    return

                self.position = shares
                self.entry_price = price
                self.stop_price = price * 0.98  # 2% stop
                self.target_price = price * 1.03  # 3% target
                
                # Create Fill object to update portfolio
                fill = fe.Fill()
                fill.order_id = 999 
                fill.symbol_id = tick.symbol_id
                fill.price = price
                fill.volume = float(shares)
                fill.side = fe.Side.BUY
                self.portfolio.on_fill(fill)
                
                print(f"  [ENTRY] BUY {shares} @ ${price:.2f} | Lower Band=${self.lower_band:.2f} | Middle=${self.middle_band:.2f} | Stop=${self.stop_price:.2f}")
                
                self.trades.append({
                    'datetime': datetime.fromtimestamp(tick.timestamp / 1e9).strftime('%Y-%m-%d %H:%M:%S'),
                    'side': 'BUY',
                    'price': round(price, 2),
                    'shares': shares,
                    'pnl': 0.0,
                })
        
        # Exit: Price reaches middle band OR stop-loss OR target
        if self.position > 0:
            exit_reason = None
            exit_price = None
            
            if price >= self.middle_band:
                exit_reason = "MIDDLE_BAND"
                exit_price = self.middle_band
            elif price <= self.stop_price:
                exit_reason = "STOP_LOSS"
                exit_price = self.stop_price
            elif price >= self.target_price:
                exit_reason = "TARGET"
                exit_price = self.target_price
            
            if exit_reason:
                pnl = (exit_price - self.entry_price) * self.position
                
                # Create Fill object to update portfolio
                fill = fe.Fill()
                fill.order_id = 999 
                fill.symbol_id = tick.symbol_id
                fill.price = exit_price
                fill.volume = float(self.position)
                fill.side = fe.Side.SELL
                self.portfolio.on_fill(fill)

                print(f"  [EXIT] SELL {self.position} @ ${exit_price:.2f} | {exit_reason} | P&L: ${pnl:+.2f}")
                
                self.trades.append({
                    'datetime': datetime.fromtimestamp(tick.timestamp / 1e9).strftime('%Y-%m-%d %H:%M:%S'),
                    'side': 'SELL',
                    'price': round(exit_price, 2),
                    'shares': self.position,
                    'pnl': round(pnl, 2),
                })
                
                self.position = 0
    
    def on_fill(self, fill):
        pass
    
    def on_bar(self, bar):
        pass
    
    def on_end(self):
        print("\n" + "="*60)
        print("Bollinger Bands Strategy Complete")
        print("="*60)
        
        results = BacktestResults(
            equity_curve=self.equity_curve,
            trades=self.trades,
            initial_capital=self.initial_cash
        )
        results.print_summary()
        
        results.export_json("results/bollinger_backtest_results.json")
        results.export_trades_csv("results/bollinger_trades.csv")


def main():
    data_file = "data/processed/reliance.bin"
    
    if not os.path.exists(data_file):
        print(f"Error: {data_file} not found.")
        print("Run: python scripts/load_datasets.py --dataset reliance --output data/processed/reliance.bin")
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
    
    strategy = BollingerBandsStrategy(engine, portfolio, risk_engine)
    
    strategy.on_start()
    
    loop = fe.EventLoop()
    loop.run(stream, strategy)
    
    strategy.on_end()


if __name__ == "__main__":
    main()