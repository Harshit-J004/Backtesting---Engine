#!/usr/bin/env python3
# filepath: /home/joelb23/BacktestingEngine/scripts/run_backtest_momentum.py
"""
Felix Backtester - Momentum Breakout Strategy
"""

import os
import sys
import json
from datetime import datetime
from collections import deque

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "python"))

import felix_engine as fe
from felix.strategy.base import Strategy


class MomentumBreakoutStrategy(Strategy):
    def __init__(self, engine: fe.MatchingEngine, portfolio: fe.Portfolio, risk_engine=None):
        self.engine = engine
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        
        self.breakout_period = 20
        self.exit_period = 10
        self.stop_loss_pct = 0.03
        self.target_pct = 0.05
        
        self.price_history = deque(maxlen=max(self.breakout_period, self.exit_period) + 1)
        self.position = 0
        self.entry_price = 0.0
        self.pending_order = None
        
        self.trades = []
        self.total_trades = 0
        self.winning_trades = 0
        
    def on_start(self):
        print("=" * 60)
        print("Momentum Breakout Strategy Started")
        print(f"Breakout Period: {self.breakout_period}")
        print(f"Exit Period: {self.exit_period}")
        print(f"Stop Loss: {self.stop_loss_pct*100:.1f}%, Target: {self.target_pct*100:.1f}%")
        print("=" * 60)
    
    def on_tick(self, tick):
        price = tick.price
        self.price_history.append(price)
        
        if len(self.price_history) < self.breakout_period:
            return
        
        recent_prices = list(self.price_history)
        high_20 = max(recent_prices[-self.breakout_period:])
        low_10 = min(recent_prices[-self.exit_period:]) if len(recent_prices) >= self.exit_period else price
        
        if len(self.price_history) % 10000 == 0:
            print(f"[Tick] Price: {price:.2f}, High20: {high_20:.2f}, Low10: {low_10:.2f}, Pos: {self.position}")
        
        if self.position > 0:
            pnl_pct = (price - self.entry_price) / self.entry_price
            
            if pnl_pct <= -self.stop_loss_pct:
                self._close_position(tick, "STOP_LOSS")
                return
            if pnl_pct >= self.target_pct:
                self._close_position(tick, "TARGET")
                return
            if price < low_10:
                self._close_position(tick, "BREAKDOWN")
                return
        else:
            if price > high_20 and len(recent_prices) > self.breakout_period:
                prev_high = max(recent_prices[-(self.breakout_period+1):-1])
                if recent_prices[-2] <= prev_high:
                    self._open_position(tick)
    
    def _open_position(self, tick):
        size = self._calculate_position_size(tick.price)
        if size <= 0:
            return
        
        order = fe.Order()
        order.symbol_id = tick.symbol_id
        order.side = fe.Side.BUY
        order.order_type = fe.OrderType.MARKET
        order.size = size
        order.price = tick.price
        order.timestamp = tick.timestamp
        
        order_id = self.engine.submit_order(order)
        if order_id > 0:
            self.pending_order = order_id
            print(f"[ENTRY] BUY order #{order_id}: {size} @ ~${tick.price:.2f}")
    
    def _close_position(self, tick, reason: str):
        if self.position <= 0:
            return
        
        order = fe.Order()
        order.symbol_id = tick.symbol_id
        order.side = fe.Side.SELL
        order.order_type = fe.OrderType.MARKET
        order.size = self.position
        order.price = tick.price
        order.timestamp = tick.timestamp
        
        order_id = self.engine.submit_order(order)
        if order_id > 0:
            pnl = (tick.price - self.entry_price) * self.position
            print(f"[EXIT-{reason}] SELL order #{order_id}: {self.position} @ ~${tick.price:.2f}, Est P&L: ${pnl:.2f}")
    
    def _calculate_position_size(self, price: float) -> int:
        available_cash = self.portfolio.cash()
        max_position_value = available_cash * 0.95
        size = int(max_position_value / price)
        return max(0, min(size, 1000))
    
    def on_fill(self, fill):
        if fill.side == fe.Side.BUY:
            self.position += fill.volume
            self.entry_price = fill.price
            self.total_trades += 1
            print(f"[FILLED] BUY {fill.volume} @ ${fill.price:.2f}")
            self.trades.append({
                'type': 'entry', 'timestamp': fill.timestamp,
                'price': fill.price, 'size': fill.volume
            })
        else:
            pnl = (fill.price - self.entry_price) * fill.volume
            self.position -= fill.volume
            if pnl > 0:
                self.winning_trades += 1
            print(f"[FILLED] SELL {fill.volume} @ ${fill.price:.2f}, P&L: ${pnl:.2f}")
            self.trades.append({
                'type': 'exit', 'timestamp': fill.timestamp,
                'price': fill.price, 'size': fill.volume, 'pnl': pnl
            })
            if self.position <= 0:
                self.entry_price = 0.0
        self.pending_order = None
    
    def on_bar(self, bar):
        pass
    
    def on_end(self):
        print("\n" + "=" * 60)
        print("Momentum Breakout Strategy Complete")
        print(f"Total Trades: {self.total_trades}, Winning: {self.winning_trades}")
        print("=" * 60)
    
    def get_trades(self):
        return self.trades


def calculate_metrics(equity_curve, initial_capital, trades):
    """Calculate backtest metrics manually"""
    import numpy as np
    
    if len(equity_curve) < 2:
        return {
            'sharpe': 0.0, 'sortino': 0.0, 'max_dd': 0.0, 'cagr': 0.0,
            'win_rate': 0.0, 'avg_win': 0.0, 'avg_loss': 0.0, 'profit_factor': 0.0
        }
    
    equity = np.array(equity_curve)
    returns = np.diff(equity) / equity[:-1]
    
    # Sharpe (annualized, assuming minute data)
    if len(returns) > 0 and np.std(returns) > 0:
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 * 390)
    else:
        sharpe = 0.0
    
    # Sortino
    neg_returns = returns[returns < 0]
    if len(neg_returns) > 0 and np.std(neg_returns) > 0:
        sortino = np.mean(returns) / np.std(neg_returns) * np.sqrt(252 * 390)
    else:
        sortino = 0.0
    
    # Max drawdown
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak
    max_dd = np.max(drawdown) if len(drawdown) > 0 else 0.0
    
    # CAGR
    if len(equity) > 1 and equity[0] > 0:
        years = len(equity) / (252 * 390)
        if years > 0:
            cagr = (equity[-1] / equity[0]) ** (1 / years) - 1
        else:
            cagr = 0.0
    else:
        cagr = 0.0
    
    # Trade stats
    wins = [t.get('pnl', 0) for t in trades if t.get('type') == 'exit' and t.get('pnl', 0) > 0]
    losses = [t.get('pnl', 0) for t in trades if t.get('type') == 'exit' and t.get('pnl', 0) < 0]
    
    total_exits = len(wins) + len(losses)
    win_rate = len(wins) / total_exits if total_exits > 0 else 0.0
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    return {
        'sharpe': sharpe, 'sortino': sortino, 'max_dd': max_dd, 'cagr': cagr,
        'win_rate': win_rate, 'avg_win': avg_win, 'avg_loss': avg_loss, 
        'profit_factor': profit_factor, 'total_trades': total_exits
    }


def main():
    data_file = "data/processed/reliance.bin"
    
    if not os.path.exists(data_file):
        print(f"Data file not found: {data_file}")
        print("Run: python3 scripts/load_datasets.py --sample --output data/processed/reliance.bin")
        return
    
    os.makedirs("results", exist_ok=True)
    
    stream = fe.DataStream()
    stream.load(data_file)
    print(f"Loaded {data_file} with {stream.size()} ticks")
    
    if stream.size() == 0:
        print("[ERROR] No data loaded!")
        return
    
    initial_capital = 100000.0
    
    # Create slippage config
    slippage = fe.SlippageConfig()
    slippage.fixed_bps = 5.0
    
    # Create latency config
    latency = fe.LatencyConfig()
    latency.strategy_latency_ns = 1000
    latency.engine_latency_ns = 500
    
    # Create matching engine
    engine = fe.MatchingEngine(slippage)
    engine.set_latency_config(latency)
    
    # Create portfolio
    portfolio = fe.Portfolio(initial_capital)
    
    # Create risk engine with RiskLimits
    risk_limits = fe.RiskLimits()
    risk_limits.max_drawdown = 0.20
    risk_limits.max_position_size = 1000
    risk_limits.max_order_size = 1000
    risk_limits.max_notional = 100000.0
    risk_limits.max_daily_loss = 5000.0
    risk_engine = fe.RiskEngine(risk_limits)
    
    print(f"Initial Capital: ${initial_capital:,.2f}")
    print(f"Slippage: {slippage.fixed_bps} bps")
    print(f"Latency: {latency.strategy_latency_ns + latency.engine_latency_ns} ns")
    print("=" * 60)
    
    # Create strategy
    strategy = MomentumBreakoutStrategy(engine, portfolio, risk_engine)
    
    # Create event loop and set components
    event_loop = fe.EventLoop()
    event_loop.set_matching_engine(engine)
    event_loop.set_portfolio(portfolio)
    event_loop.set_risk_engine(risk_engine)
    
    # Run backtest
    event_loop.run(stream, strategy, engine, portfolio)
    
    # Get results
    final_equity = portfolio.equity()
    total_pnl = final_equity - initial_capital
    total_return = (total_pnl / initial_capital) * 100
    
    equity_curve = portfolio.get_equity_values()
    timestamps = portfolio.get_timestamps()
    trades = strategy.get_trades()
    
    # Calculate metrics
    metrics = calculate_metrics(equity_curve, initial_capital, trades)
    
    # Duration in days
    if len(timestamps) >= 2:
        duration_ns = timestamps[-1] - timestamps[0]
        duration_days = duration_ns / (1e9 * 86400)
    else:
        duration_days = 0
    
    print("\n" + "=" * 50)
    print("BACKTEST RESULTS")
    print("=" * 50)
    print(f"Duration:           {duration_days:.0f} days")
    print(f"Initial Capital:    ${initial_capital:,.2f}")
    print(f"Final Equity:       ${final_equity:,.2f}")
    print(f"Total P&L:          ${'+' if total_pnl >= 0 else ''}{total_pnl:,.2f} ({total_return:+.2f}%)")
    print("-" * 50)
    print(f"Sharpe Ratio:       {metrics['sharpe']:.2f}")
    print(f"Sortino Ratio:      {metrics['sortino']:.2f}")
    print(f"Max Drawdown:       {metrics['max_dd']*100:.2f}%")
    print(f"CAGR:               {metrics['cagr']*100:.2f}%")
    print("-" * 50)
    print(f"Total Trades:       {metrics['total_trades']}")
    print(f"Win Rate:           {metrics['win_rate']*100:.1f}%")
    print(f"Avg Win:            ${metrics['avg_win']:,.2f}")
    print(f"Avg Loss:           ${metrics['avg_loss']:,.2f}")
    print(f"Profit Factor:      {metrics['profit_factor']:.2f}")
    print("=" * 50)
    
    # Export results
    results_data = {
        'initial_capital': initial_capital,
        'final_equity': final_equity,
        'total_pnl': total_pnl,
        'total_return_pct': total_return,
        'duration_days': duration_days,
        'metrics': metrics,
        'num_ticks': stream.size(),
        'timestamp': datetime.now().isoformat()
    }
    
    with open("results/momentum_backtest_results.json", "w") as f:
        json.dump(results_data, f, indent=2)
    print("Results exported to results/momentum_backtest_results.json")
    
    if trades:
        with open("results/momentum_trades.json", "w") as f:
            json.dump(trades, f, indent=2, default=str)
        print("Trades exported to results/momentum_trades.json")
    else:
        print("No trades to export.")
    
    print(f"\n[Stats] Ticks: {event_loop.ticks_processed()}, Orders: {event_loop.orders_processed()}, Fills: {event_loop.fills_generated()}")


if __name__ == "__main__":
    main()