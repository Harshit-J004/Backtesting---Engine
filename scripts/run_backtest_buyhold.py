#!/usr/bin/env python3
# filepath: /home/joelb23/BacktestingEngine/scripts/run_backtest_buyhold.py
"""
Felix Backtester - Buy & Hold Strategy (System Verification)
"""

import os
import sys
import json
import time
import struct
from datetime import datetime

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


class BuyAndHoldStrategy(Strategy):
    """Simple buy and hold - buy once at start, never sell"""
    
    def __init__(self, engine: fe.MatchingEngine, portfolio: fe.Portfolio):
        self.engine = engine
        self.portfolio = portfolio
        self.bought = False
        self.entry_price = 0.0
        self.shares = 0
        self.tick_count = 0
        self.first_price = None
        self.last_price = None
        self.first_timestamp = None
        self.last_timestamp = None
        
    def on_start(self):
        print("=" * 60)
        print("Buy & Hold Strategy (System Verification)")
        print("=" * 60)
    
    def on_tick(self, tick):
        self.tick_count += 1
        self.last_price = tick.price
        self.last_timestamp = tick.timestamp
        
        if self.first_price is None:
            self.first_price = tick.price
            self.first_timestamp = tick.timestamp
        
        # Buy once on first tick
        if not self.bought:
            available_cash = self.portfolio.cash()
            size = int((available_cash * 0.95) / tick.price)
            
            if size > 0:
                order = fe.Order()
                order.symbol_id = tick.symbol_id
                order.side = fe.Side.BUY
                order.order_type = fe.OrderType.MARKET
                order.size = size
                order.price = tick.price
                order.timestamp = tick.timestamp
                
                order_id = self.engine.submit_order(order)
                if order_id > 0:
                    print(f"[BUY] Order #{order_id}: {size} shares @ ~${tick.price:.2f}")
                    self.bought = True
        
        # Log progress every 100k ticks
        if self.tick_count % 100000 == 0:
            equity = self.portfolio.equity()
            print(f"[Tick {self.tick_count:,}] Price: ${tick.price:.2f}, Equity: ${equity:,.2f}")
    
    def on_fill(self, fill):
        if fill.side == fe.Side.BUY:
            self.shares = fill.volume
            self.entry_price = fill.price
            print(f"[FILLED] BUY {fill.volume} @ ${fill.price:.2f}")
    
    def on_bar(self, bar):
        pass
    
    def on_end(self):
        if self.shares > 0 and self.last_price:
            unrealized_pnl = (self.last_price - self.entry_price) * self.shares
            print(f"\n[END] Holding {self.shares} shares")
            print(f"      Entry: ${self.entry_price:.2f}, Current: ${self.last_price:.2f}")
            print(f"      Unrealized P&L: ${unrealized_pnl:,.2f}")
    
    def get_stats(self):
        return {
            'tick_count': self.tick_count,
            'first_price': self.first_price,
            'last_price': self.last_price,
            'first_timestamp': self.first_timestamp,
            'last_timestamp': self.last_timestamp,
            'shares': self.shares,
            'entry_price': self.entry_price
        }


def main():
    data_file = "data/processed/reliance.bin"
    
    if not os.path.exists(data_file):
        print(f"Data file not found: {data_file}")
        return
    
    os.makedirs("results", exist_ok=True)
    
    total_start = time.perf_counter()
    
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
    print(f"Data: {data_start_dt.strftime('%Y-%m-%d')} to {data_end_dt.strftime('%Y-%m-%d')} ({data_duration_days:.0f} days)")
    print(f"Price: ${tick_info['first']['price']:.2f} → ${tick_info['last']['price']:.2f} ({((tick_info['last']['price']/tick_info['first']['price'])-1)*100:+.1f}%)")
    
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
    
    # Disable risk limits for buy-and-hold verification
    risk_limits = fe.RiskLimits()
    risk_limits.max_drawdown = 1.0  # 100% - effectively disabled
    risk_limits.max_position_size = 10000
    risk_limits.max_order_size = 10000
    risk_limits.max_notional = 1000000.0
    risk_limits.max_daily_loss = 1000000.0
    risk_engine = fe.RiskEngine(risk_limits)
    
    strategy = BuyAndHoldStrategy(engine, portfolio)
    
    event_loop = fe.EventLoop()
    event_loop.set_matching_engine(engine)
    event_loop.set_portfolio(portfolio)
    event_loop.set_risk_engine(risk_engine)
    
    setup_time = time.perf_counter() - setup_start
    
    print(f"\nInitial Capital: ${initial_capital:,.2f}")
    
    backtest_start = time.perf_counter()
    event_loop.run(stream, strategy, engine, portfolio)
    backtest_time = time.perf_counter() - backtest_start
    
    results_start = time.perf_counter()
    
    final_equity = portfolio.equity()
    total_pnl = final_equity - initial_capital
    total_return_pct = (total_pnl / initial_capital) * 100
    
    stats = strategy.get_stats()
    
    results_time = time.perf_counter() - results_start
    total_time = time.perf_counter() - total_start
    
    ticks_per_sec = num_ticks / backtest_time if backtest_time > 0 else 0
    us_per_tick = (backtest_time * 1e6) / num_ticks if num_ticks > 0 else 0
    
    # Calculate expected P&L
    expected_pnl = stats['shares'] * (stats['last_price'] - stats['entry_price']) if stats['shares'] > 0 else 0
    
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS - BUY & HOLD")
    print("=" * 60)
    
    print("\n--- VERIFICATION ---")
    print(f"Entry Price:           ${stats['entry_price']:.2f}")
    print(f"Exit Price:            ${stats['last_price']:.2f}")
    print(f"Price Change:          {((stats['last_price']/stats['entry_price'])-1)*100:+.1f}%")
    print(f"Shares:                {stats['shares']}")
    print(f"Expected P&L:          ${expected_pnl:,.2f}")
    print(f"Actual P&L:            ${total_pnl:,.2f}")
    print(f"Match:                 {'✓ YES' if abs(expected_pnl - total_pnl) < 100 else '✗ NO (check slippage)'}")
    
    print("\n--- OVERVIEW ---")
    print(f"Initial Capital:       ${initial_capital:,.2f}")
    print(f"Final Equity:          ${final_equity:,.2f}")
    print(f"Total P&L:             ${total_pnl:+,.2f} ({total_return_pct:+.2f}%)")
    print(f"Ticks Processed:       {stats['tick_count']:,} / {num_ticks:,}")
    
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
    print(f"Latency per tick:      {us_per_tick:.2f} μs")
    print(f"Ticks processed:       {num_ticks:,}")
    print("=" * 60)
    
    print(f"\n[Engine Stats] Ticks: {event_loop.ticks_processed()}, Orders: {event_loop.orders_processed()}, Fills: {event_loop.fills_generated()}")


if __name__ == "__main__":
    main()