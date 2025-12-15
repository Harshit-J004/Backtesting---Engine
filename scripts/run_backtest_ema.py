#!/usr/bin/env python3
# filepath: /home/joelb23/BacktestingEngine/scripts/run_backtest_ema.py
"""
Felix Backtester - EMA Crossover Strategy (9/14)
"""

import os
import sys
import json
import time
import struct
from datetime import datetime
from collections import deque

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "python"))

import numpy as np
import felix_engine as fe
from felix.strategy.base import Strategy

TICK_FORMAT = '<QIfffffII'
TICK_SIZE = 40


def ns_to_datetime(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9)


def read_first_last_ticks(filepath: str):
    with open(filepath, 'rb') as f:
        data = f.read(TICK_SIZE)
        first = struct.unpack(TICK_FORMAT, data)
        
        file_size = os.path.getsize(filepath)
        num_ticks = file_size // TICK_SIZE
        f.seek((num_ticks - 1) * TICK_SIZE)
        data = f.read(TICK_SIZE)
        last = struct.unpack(TICK_FORMAT, data)
    
    return {
        'first': {'timestamp': first[0], 'price': first[2]},
        'last': {'timestamp': last[0], 'price': last[2]},
        'num_ticks': num_ticks
    }


class EMACrossoverStrategy(Strategy):
    def __init__(self, engine: fe.MatchingEngine, portfolio: fe.Portfolio):
        self.engine = engine
        self.portfolio = portfolio
        
        self.fast_period = 9
        self.slow_period = 14
        
        self.prices = deque(maxlen=self.slow_period + 1)
        self.ema_fast = None
        self.ema_slow = None
        self.prev_ema_fast = None
        self.prev_ema_slow = None
        
        self.position = 0
        self.entry_price = 0.0
        
        self.trades = []
        self.tick_count = 0
        self.first_price = None
        self.last_price = None
        self.first_timestamp = None
        self.last_timestamp = None
        
    def on_start(self):
        print("=" * 60)
        print("EMA Crossover Strategy (9/14)")
        print("=" * 60)
    
    def _calc_ema(self, prices, period):
        if len(prices) < period:
            return None
        mult = 2 / (period + 1)
        ema = prices[0]
        for p in list(prices)[1:]:
            ema = (p - ema) * mult + ema
        return ema
    
    def on_tick(self, tick):
        price = tick.price
        self.prices.append(price)
        self.tick_count += 1
        self.last_price = price
        self.last_timestamp = tick.timestamp
        
        if self.first_price is None:
            self.first_price = price
            self.first_timestamp = tick.timestamp
        
        if len(self.prices) < self.slow_period:
            return
        
        self.prev_ema_fast = self.ema_fast
        self.prev_ema_slow = self.ema_slow
        
        self.ema_fast = self._calc_ema(list(self.prices)[-self.fast_period:], self.fast_period)
        self.ema_slow = self._calc_ema(list(self.prices), self.slow_period)
        
        if self.prev_ema_fast is None or self.prev_ema_slow is None:
            return
        
        if self.tick_count % 100000 == 0:
            equity = self.portfolio.equity()
            print(f"[Tick {self.tick_count:,}] Price: ${price:.2f}, EMA9: ${self.ema_fast:.2f}, EMA14: ${self.ema_slow:.2f}, Pos: {self.position}, Equity: ${equity:,.2f}")
        
        was_below = self.prev_ema_fast < self.prev_ema_slow
        is_above = self.ema_fast > self.ema_slow
        was_above = self.prev_ema_fast > self.prev_ema_slow
        is_below = self.ema_fast < self.ema_slow
        
        if was_below and is_above and self.position == 0:
            self._open_position(tick)
        elif was_above and is_below and self.position > 0:
            self._close_position(tick)
    
    def _open_position(self, tick):
        available_cash = self.portfolio.cash()
        size = int((available_cash * 0.95) / tick.price)
        size = max(0, min(size, 1000))
        
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
            print(f"[BUY] Order #{order_id}: {size} @ ~${tick.price:.2f}")
    
    def _close_position(self, tick):
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
            print(f"[SELL] Order #{order_id}: {self.position} @ ~${tick.price:.2f}, Est P&L: ${pnl:.2f}")
    
    def on_fill(self, fill):
        if fill.side == fe.Side.BUY:
            self.position += fill.volume
            self.entry_price = fill.price
            self.trades.append({'type': 'entry', 'timestamp': fill.timestamp, 'price': fill.price, 'size': fill.volume})
        else:
            pnl = (fill.price - self.entry_price) * fill.volume
            self.position -= fill.volume
            self.trades.append({'type': 'exit', 'timestamp': fill.timestamp, 'price': fill.price, 'size': fill.volume, 'pnl': pnl})
            if self.position <= 0:
                self.entry_price = 0.0
    
    def on_bar(self, bar):
        pass
    
    def on_end(self):
        exits = [t for t in self.trades if t.get('type') == 'exit']
        wins = len([t for t in exits if t.get('pnl', 0) > 0])
        print("\n" + "=" * 60)
        print(f"EMA Crossover Complete: {len(exits)} trades, {wins} wins")
        print("=" * 60)
    
    def get_trades(self):
        return self.trades
    
    def get_stats(self):
        return {
            'tick_count': self.tick_count,
            'first_price': self.first_price,
            'last_price': self.last_price,
            'first_timestamp': self.first_timestamp,
            'last_timestamp': self.last_timestamp
        }


def calculate_metrics(equity_curve, initial_capital, trades, duration_years):
    """Calculate all performance metrics"""
    if len(equity_curve) < 2 or duration_years <= 0:
        return {k: 0 for k in ['sharpe', 'sortino', 'calmar', 'max_dd', 'cagr', 'total_return', 'volatility',
                               'win_rate', 'avg_win', 'avg_loss', 'profit_factor', 'total_trades',
                               'max_consecutive_wins', 'max_consecutive_losses', 'expectancy', 'gross_profit', 'gross_loss']}
    
    equity = np.array(equity_curve)
    returns = np.diff(equity) / equity[:-1]
    returns = returns[np.isfinite(returns)]
    
    periods_per_year = len(equity_curve) / duration_years if duration_years > 0 else 252
    
    # Risk metrics
    total_return = (equity[-1] - initial_capital) / initial_capital
    volatility = np.std(returns) * np.sqrt(periods_per_year) if len(returns) > 0 and np.std(returns) > 0 else 0
    sharpe = np.mean(returns) / np.std(returns) * np.sqrt(periods_per_year) if np.std(returns) > 0 else 0
    
    neg_ret = returns[returns < 0]
    sortino = np.mean(returns) / np.std(neg_ret) * np.sqrt(periods_per_year) if len(neg_ret) > 0 and np.std(neg_ret) > 0 else 0
    
    # Drawdown
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak
    max_dd = np.max(drawdown) if len(drawdown) > 0 else 0
    
    # CAGR and Calmar
    cagr = (equity[-1] / equity[0]) ** (1 / duration_years) - 1 if duration_years > 0 and equity[0] > 0 else 0
    calmar = cagr / max_dd if max_dd > 0 else 0
    
    # Trade statistics
    exits = [t for t in trades if t.get('type') == 'exit']
    wins = [t['pnl'] for t in exits if t.get('pnl', 0) > 0]
    losses = [t['pnl'] for t in exits if t.get('pnl', 0) < 0]
    
    total_trades = len(exits)
    win_rate = len(wins) / total_trades if total_trades > 0 else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    expectancy = np.mean([t.get('pnl', 0) for t in exits]) if exits else 0
    
    # Consecutive wins/losses
    max_consecutive_wins = max_consecutive_losses = current_wins = current_losses = 0
    for t in exits:
        if t.get('pnl', 0) > 0:
            current_wins += 1
            current_losses = 0
            max_consecutive_wins = max(max_consecutive_wins, current_wins)
        elif t.get('pnl', 0) < 0:
            current_losses += 1
            current_wins = 0
            max_consecutive_losses = max(max_consecutive_losses, current_losses)
    
    return {
        'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar, 'max_dd': max_dd, 'cagr': cagr,
        'total_return': total_return, 'volatility': volatility, 'win_rate': win_rate, 'avg_win': avg_win,
        'avg_loss': avg_loss, 'profit_factor': profit_factor, 'total_trades': total_trades,
        'max_consecutive_wins': max_consecutive_wins, 'max_consecutive_losses': max_consecutive_losses,
        'expectancy': expectancy, 'gross_profit': gross_profit, 'gross_loss': gross_loss
    }


def main():
    data_file = "data/processed/reliance.bin"
    
    if not os.path.exists(data_file):
        print(f"Data file not found: {data_file}")
        return
    
    os.makedirs("results", exist_ok=True)
    
    total_start = time.perf_counter()
    
    # Get data info
    tick_info = read_first_last_ticks(data_file)
    data_start_dt = ns_to_datetime(tick_info['first']['timestamp'])
    data_end_dt = ns_to_datetime(tick_info['last']['timestamp'])
    data_duration_days = (data_end_dt - data_start_dt).total_seconds() / 86400
    data_duration_years = data_duration_days / 365.25
    
    load_start = time.perf_counter()
    stream = fe.DataStream()
    stream.load(data_file)
    load_time = time.perf_counter() - load_start
    
    num_ticks = stream.size()
    print(f"Loaded {num_ticks:,} ticks in {load_time*1000:.2f} ms")
    print(f"Data period: {data_start_dt.strftime('%Y-%m-%d')} to {data_end_dt.strftime('%Y-%m-%d')} ({data_duration_days:.0f} days)")
    print(f"Price: ${tick_info['first']['price']:.2f} → ${tick_info['last']['price']:.2f} ({((tick_info['last']['price']/tick_info['first']['price'])-1)*100:+.1f}%)")
    
    if num_ticks == 0:
        return
    
    initial_capital = 100000.0
    
    setup_start = time.perf_counter()
    
    slippage = fe.SlippageConfig()
    slippage.fixed_bps = 5.0
    
    latency = fe.LatencyConfig()
    latency.strategy_latency_ns = 1000
    latency.engine_latency_ns = 500
    
    engine = fe.MatchingEngine(slippage)
    engine.set_latency_config(latency)
    
    portfolio = fe.Portfolio(initial_capital)
    
    # Risk limits - relaxed for testing
    risk_limits = fe.RiskLimits()
    risk_limits.max_drawdown = 0.99  # Allow up to 99% drawdown
    risk_limits.max_position_size = 1000
    risk_limits.max_order_size = 1000
    risk_limits.max_notional = 500000.0
    risk_limits.max_daily_loss = 500000.0
    risk_engine = fe.RiskEngine(risk_limits)
    
    strategy = EMACrossoverStrategy(engine, portfolio)
    
    event_loop = fe.EventLoop()
    event_loop.set_matching_engine(engine)
    event_loop.set_portfolio(portfolio)
    event_loop.set_risk_engine(risk_engine)
    
    setup_time = time.perf_counter() - setup_start
    
    print(f"\nInitial Capital: ${initial_capital:,.2f}")
    print(f"Slippage: {slippage.fixed_bps} bps")
    
    backtest_start = time.perf_counter()
    event_loop.run(stream, strategy, engine, portfolio)
    backtest_time = time.perf_counter() - backtest_start
    
    results_start = time.perf_counter()
    
    final_equity = portfolio.equity()
    total_pnl = final_equity - initial_capital
    total_return_pct = (total_pnl / initial_capital) * 100
    
    equity_curve = portfolio.get_equity_values()
    timestamps = portfolio.get_timestamps()
    trades = strategy.get_trades()
    stats = strategy.get_stats()
    
    # Calculate actual duration from strategy timestamps
    if stats['first_timestamp'] and stats['last_timestamp']:
        bt_start_dt = ns_to_datetime(stats['first_timestamp'])
        bt_end_dt = ns_to_datetime(stats['last_timestamp'])
        bt_duration_days = (bt_end_dt - bt_start_dt).total_seconds() / 86400
        bt_duration_years = bt_duration_days / 365.25
    else:
        bt_duration_days = data_duration_days
        bt_duration_years = data_duration_years
    
    metrics = calculate_metrics(equity_curve, initial_capital, trades, bt_duration_years)
    
    results_time = time.perf_counter() - results_start
    total_time = time.perf_counter() - total_start
    
    ticks_per_sec = num_ticks / backtest_time if backtest_time > 0 else 0
    ns_per_tick = (backtest_time * 1e9) / num_ticks if num_ticks > 0 else 0
    us_per_tick = ns_per_tick / 1000
    
    # Print results
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS - EMA CROSSOVER (9/14)")
    print("=" * 60)
    
    print("\n--- DATA INFO ---")
    print(f"Data Period:           {data_start_dt.strftime('%Y-%m-%d')} to {data_end_dt.strftime('%Y-%m-%d')}")
    print(f"Data Duration:         {data_duration_days:.0f} days ({data_duration_years:.2f} years)")
    print(f"Ticks Processed:       {stats['tick_count']:,} / {num_ticks:,}")
    
    print("\n--- OVERVIEW ---")
    print(f"Initial Capital:       ${initial_capital:,.2f}")
    print(f"Final Equity:          ${final_equity:,.2f}")
    print(f"Total P&L:             ${'+' if total_pnl >= 0 else ''}{total_pnl:,.2f} ({total_return_pct:+.2f}%)")
    
    print("\n--- RISK METRICS ---")
    print(f"Sharpe Ratio:          {metrics['sharpe']:.3f}")
    print(f"Sortino Ratio:         {metrics['sortino']:.3f}")
    print(f"Calmar Ratio:          {metrics['calmar']:.3f}")
    print(f"Max Drawdown:          {metrics['max_dd']*100:.2f}%")
    print(f"Volatility (Ann.):     {metrics['volatility']*100:.2f}%")
    
    print("\n--- RETURN METRICS ---")
    print(f"Total Return:          {metrics['total_return']*100:.2f}%")
    print(f"CAGR:                  {metrics['cagr']*100:.2f}%")
    
    print("\n--- TRADE STATISTICS ---")
    print(f"Total Trades:          {metrics['total_trades']}")
    print(f"Win Rate:              {metrics['win_rate']*100:.1f}%")
    print(f"Avg Win:               ${metrics['avg_win']:,.2f}")
    print(f"Avg Loss:              ${metrics['avg_loss']:,.2f}")
    print(f"Profit Factor:         {metrics['profit_factor']:.2f}")
    print(f"Expectancy:            ${metrics['expectancy']:,.2f}")
    print(f"Gross Profit:          ${metrics['gross_profit']:,.2f}")
    print(f"Gross Loss:            ${metrics['gross_loss']:,.2f}")
    print(f"Max Consecutive Wins:  {metrics['max_consecutive_wins']}")
    print(f"Max Consecutive Losses:{metrics['max_consecutive_losses']}")
    
    print("\n" + "=" * 60)
    print("PERFORMANCE TIMING")
    print("=" * 60)
    print(f"Data Loading:          {load_time*1000:>10.2f} ms")
    print(f"Setup:                 {setup_time*1000:>10.2f} ms")
    print(f"Backtest Execution:    {backtest_time*1000:>10.2f} ms")
    print(f"Results Calculation:   {results_time*1000:>10.2f} ms")
    print(f"{'─' * 40}")
    print(f"TOTAL TIME:            {total_time*1000:>10.2f} ms")
    print(f"")
    print(f"Throughput:            {ticks_per_sec:,.0f} ticks/sec")
    print(f"Latency per tick:      {us_per_tick:.2f} μs ({ns_per_tick:.0f} ns)")
    print(f"Ticks processed:       {num_ticks:,}")
    print("=" * 60)
    
    # Performance assessment
    print("\n--- PERFORMANCE ASSESSMENT ---")
    if us_per_tick < 1.0:
        print(f"Latency: EXCELLENT (<1μs)")
    elif us_per_tick < 2.5:
        print(f"Latency: GOOD (1-2.5μs) - Expected with Python callbacks")
    elif us_per_tick < 5.0:
        print(f"Latency: ACCEPTABLE (2.5-5μs)")
    else:
        print(f"Latency: NEEDS OPTIMIZATION (>5μs)")
    
    print(f"\n[Engine Stats] Ticks: {event_loop.ticks_processed()}, Orders: {event_loop.orders_processed()}, Fills: {event_loop.fills_generated()}")
    
    # Export results
    results_data = {
        'strategy': 'EMA Crossover 9/14',
        'data_period': {
            'start': data_start_dt.isoformat(),
            'end': data_end_dt.isoformat(),
            'duration_days': data_duration_days,
            'duration_years': data_duration_years
        },
        'initial_capital': initial_capital,
        'final_equity': final_equity,
        'total_pnl': total_pnl,
        'metrics': metrics,
        'timing': {
            'load_ms': load_time * 1000,
            'setup_ms': setup_time * 1000,
            'backtest_ms': backtest_time * 1000,
            'results_ms': results_time * 1000,
            'total_ms': total_time * 1000,
            'ticks_per_sec': ticks_per_sec,
            'us_per_tick': us_per_tick,
            'ns_per_tick': ns_per_tick
        },
        'timestamp': datetime.now().isoformat()
    }
    
    with open("results/ema_backtest_results.json", "w") as f:
        json.dump(results_data, f, indent=2)
    print("\nResults exported to results/ema_backtest_results.json")
    
    if trades:
        with open("results/ema_trades.json", "w") as f:
            json.dump(trades, f, indent=2, default=str)
        print(f"Trades exported to results/ema_trades.json ({len(trades)} records)")


if __name__ == "__main__":
    main()