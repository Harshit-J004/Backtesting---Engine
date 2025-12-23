#!/usr/bin/env python3
# filepath: /home/joelb23/BacktestingEngine/scripts/run_combined_strat.py
"""
Felix Backtester - Combined Strategy (Bollinger Bands + 3EMA/ATR)
"""

import os
import sys
import json
from datetime import datetime
import struct
from collections import deque

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "python"))

import felix_engine as fe
from felix.strategy.base import Strategy


class BollingerBandsStrategy(Strategy):
    """Strategy 1: Bollinger Bands mean reversion (LONG ONLY)"""
    
    def __init__(self, engine: fe.MatchingEngine, portfolio: fe.Portfolio, risk_engine=None):
        self.engine = engine
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        
        self.length = 20
        self.mult = 2.5
        self.pct_equity = 0.5
        
        self.price_history = deque(maxlen=self.length + 1)
        self.position = 0
        self.entry_price = 0.0
        self.entry_side = 0  # 1=long, -1=short, 0=flat
        
        self.trades = []
        self.total_trades = 0
        self.winning_trades = 0
        
    def on_start(self):
        print("=" * 60)
        print("Bollinger Bands Strategy Started")
        print(f"Length: {self.length}, Multiplier: {self.mult}")
        print(f"Position Size: {self.pct_equity*100:.0f}% of equity")
        print("=" * 60)
    
    def on_tick(self, tick):
        # Safety checks
        if self.portfolio.equity() <= 0:
            return
        
        price = tick.price
        self.price_history.append(price)
        
        if len(self.price_history) < self.length:
            return
        
        prices = list(self.price_history)[-self.length:]
        sma = sum(prices) / len(prices)
        variance = sum((p - sma) ** 2 for p in prices) / len(prices)
        std = variance ** 0.5
        
        upper = sma + (self.mult * std)
        lower = sma - (self.mult * std)
        
        prev_price = prices[-2] if len(prices) > 1 else price
        
        if self.entry_side == 1:  # Long position
            if price < upper and prev_price >= upper:
                self._close_position(tick, "UPPER_CROSS")
        elif self.entry_side == 0:  # Flat (LONG ONLY - removed short)
            if prev_price < lower and price > lower:
                self._open_long(tick)
    
    def _open_long(self, tick):
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
            print(f"[BB-LONG] BUY order #{order_id}: {size} @ ~${tick.price:.2f}")
    
    def _close_position(self, tick, reason: str):
        if self.position == 0:
            return
        
        order = fe.Order()
        order.symbol_id = tick.symbol_id
        order.side = fe.Side.SELL if self.entry_side == 1 else fe.Side.BUY
        order.order_type = fe.OrderType.MARKET
        order.size = abs(self.position)
        order.price = tick.price
        order.timestamp = tick.timestamp
        
        order_id = self.engine.submit_order(order)
        if order_id > 0:
            if self.entry_side == 1:
                pnl = (tick.price - self.entry_price) * self.position
            else:
                pnl = (self.entry_price - tick.price) * abs(self.position)
            print(f"[BB-EXIT-{reason}] order #{order_id}: {abs(self.position)} @ ~${tick.price:.2f}, Est P&L: ${pnl:.2f}")
    
    def _calculate_position_size(self, price: float) -> int:
        available_cash = self.portfolio.cash()
        if available_cash <= 100:  # Minimum cash buffer
            return 0
        max_position_value = available_cash * self.pct_equity
        size = int(max_position_value / price)
        return max(0, min(size, 1000))
    
    def on_fill(self, fill):
        if fill.side == fe.Side.BUY:
            if self.entry_side == -1:  # Closing short
                pnl = (self.entry_price - fill.price) * fill.volume
                self.position = 0
                self.entry_side = 0
                if pnl > 0:
                    self.winning_trades += 1
                self.trades.append({
                    'type': 'exit', 'strategy': 'BB', 'timestamp': fill.timestamp,
                    'price': fill.price, 'size': fill.volume, 'pnl': pnl
                })
                self.entry_price = 0.0
            else:  # Opening long
                self.position = fill.volume
                self.entry_price = fill.price
                self.entry_side = 1
                self.total_trades += 1
                self.trades.append({
                    'type': 'entry', 'strategy': 'BB', 'side': 'LONG',
                    'timestamp': fill.timestamp, 'price': fill.price, 'size': fill.volume
                })
        else:  # SELL
            if self.entry_side == 1:  # Closing long
                pnl = (fill.price - self.entry_price) * fill.volume
                self.position = 0
                self.entry_side = 0
                if pnl > 0:
                    self.winning_trades += 1
                self.trades.append({
                    'type': 'exit', 'strategy': 'BB', 'timestamp': fill.timestamp,
                    'price': fill.price, 'size': fill.volume, 'pnl': pnl
                })
                self.entry_price = 0.0
            else:  # Opening short
                self.position = -fill.volume
                self.entry_price = fill.price
                self.entry_side = -1
                self.total_trades += 1
                self.trades.append({
                    'type': 'entry', 'strategy': 'BB', 'side': 'SHORT',
                    'timestamp': fill.timestamp, 'price': fill.price, 'size': fill.volume
                })
    
    def on_bar(self, bar):
        pass
    
    def on_end(self):
        print(f"[BB] Complete - Trades: {self.total_trades}, Wins: {self.winning_trades}")
    
    def get_trades(self):
        return self.trades


class ThreeEMAStrategy(Strategy):
    """Strategy 2: 3EMA Crossover with ATR-based TP/SL (LONG ONLY)"""
    
    def __init__(self, engine: fe.MatchingEngine, portfolio: fe.Portfolio, risk_engine=None):
        self.engine = engine
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        
        self.slow_ema_len = 30
        self.mid_ema_len = 12
        self.fast_ema_len = 7
        self.atr_len = 7
        self.tp_atr_mult = 4
        self.sl_atr_mult = 1
        self.pct_equity = 0.1
        
        self.price_history = deque(maxlen=self.slow_ema_len + 5)
        self.high_history = deque(maxlen=self.atr_len + 1)
        self.low_history = deque(maxlen=self.atr_len + 1)
        
        self.ema_fast = 0.0
        self.ema_mid = 0.0
        self.ema_slow = 0.0
        self.prev_ema_fast = 0.0
        self.prev_ema_mid = 0.0
        self.prev_ema_slow = 0.0
        
        self.position = 0
        self.entry_price = 0.0
        self.take_profit = 0.0
        self.stop_loss = 0.0
        
        self.trades = []
        self.total_trades = 0
        self.winning_trades = 0
        self.tick_count = 0
        
    def on_start(self):
        print("=" * 60)
        print("3EMA + ATR Strategy Started")
        print(f"EMAs: Fast={self.fast_ema_len}, Mid={self.mid_ema_len}, Slow={self.slow_ema_len}")
        print(f"ATR Length: {self.atr_len}, TP: {self.tp_atr_mult}x, SL: {self.sl_atr_mult}x")
        print("=" * 60)
    
    def _calc_ema(self, price: float, prev_ema: float, period: int) -> float:
        if prev_ema == 0.0:
            return price
        alpha = 2.0 / (period + 1)
        return price * alpha + prev_ema * (1 - alpha)
    
    def _calc_rma(self, value: float, prev_rma: float, period: int) -> float:
        if prev_rma == 0.0:
            return value
        alpha = 1.0 / period
        return value * alpha + prev_rma * (1 - alpha)
    
    def _calc_atr(self) -> float:
        if len(self.high_history) < 2 or len(self.low_history) < 2:
            return 0.0
        
        highs = list(self.high_history)
        lows = list(self.low_history)
        closes = list(self.price_history)
        
        if len(closes) < 2:
            return highs[-1] - lows[-1]
        
        tr = max(
            highs[-1] - lows[-1],
            abs(highs[-1] - closes[-2]),
            abs(lows[-1] - closes[-2])
        )
        return tr
    
    def on_tick(self, tick):
        # Safety checks
        if self.portfolio.equity() <= 0:
            return
        
        self.tick_count += 1
        price = tick.price
        
        self.price_history.append(price)
        self.high_history.append(tick.price * 1.001)  # Approximate high
        self.low_history.append(tick.price * 0.999)   # Approximate low
        
        if len(self.price_history) < self.slow_ema_len:
            return
        
        self.prev_ema_fast = self.ema_fast
        self.prev_ema_mid = self.ema_mid
        self.prev_ema_slow = self.ema_slow
        
        self.ema_fast = self._calc_ema(price, self.ema_fast, self.fast_ema_len)
        self.ema_mid = self._calc_ema(price, self.ema_mid, self.mid_ema_len)
        self.ema_slow = self._calc_ema(price, self.ema_slow, self.slow_ema_len)
        
        if self.position > 0:
            if price <= self.stop_loss:
                self._close_position(tick, "STOP_LOSS")
                return
            if price >= self.take_profit:
                self._close_position(tick, "TAKE_PROFIT")
                return
            
            # EMA crossunder exit: fast crosses below mid
            if self.prev_ema_fast >= self.prev_ema_mid and self.ema_fast < self.ema_mid:
                self._close_position(tick, "EMA_EXIT")
                return
        else:
            # Entry: mid crosses above slow
            if self.prev_ema_mid <= self.prev_ema_slow and self.ema_mid > self.ema_slow:
                self._open_position(tick)
    
    def _open_position(self, tick):
        size = self._calculate_position_size(tick.price)
        if size <= 0:
            return
        
        atr = self._calc_atr()
        if atr <= 0:
            atr = tick.price * 0.01
        
        self.take_profit = tick.price + (atr * self.tp_atr_mult)
        self.stop_loss = tick.price - (atr * self.sl_atr_mult)
        
        order = fe.Order()
        order.symbol_id = tick.symbol_id
        order.side = fe.Side.BUY
        order.order_type = fe.OrderType.MARKET
        order.size = size
        order.price = tick.price
        order.timestamp = tick.timestamp
        
        order_id = self.engine.submit_order(order)
        if order_id > 0:
            print(f"[3EMA-ENTRY] BUY order #{order_id}: {size} @ ~${tick.price:.2f}, TP=${self.take_profit:.2f}, SL=${self.stop_loss:.2f}")
    
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
            print(f"[3EMA-EXIT-{reason}] SELL order #{order_id}: {self.position} @ ~${tick.price:.2f}, Est P&L: ${pnl:.2f}")
    
    def _calculate_position_size(self, price: float) -> int:
        available_cash = self.portfolio.cash()
        if available_cash <= 100:  # Minimum cash buffer
            return 0
        max_position_value = available_cash * self.pct_equity
        size = int(max_position_value / price)
        return max(0, min(size, 1000))
    
    def on_fill(self, fill):
        if fill.side == fe.Side.BUY:
            self.position += fill.volume
            self.entry_price = fill.price
            self.total_trades += 1
            self.trades.append({
                'type': 'entry', 'strategy': '3EMA', 'timestamp': fill.timestamp,
                'price': fill.price, 'size': fill.volume
            })
        else:
            pnl = (fill.price - self.entry_price) * fill.volume
            self.position -= fill.volume
            if pnl > 0:
                self.winning_trades += 1
            self.trades.append({
                'type': 'exit', 'strategy': '3EMA', 'timestamp': fill.timestamp,
                'price': fill.price, 'size': fill.volume, 'pnl': pnl
            })
            if self.position <= 0:
                self.entry_price = 0.0
                self.take_profit = 0.0
                self.stop_loss = 0.0
    
    def on_bar(self, bar):
        pass
    
    def on_end(self):
        print(f"[3EMA] Complete - Trades: {self.total_trades}, Wins: {self.winning_trades}")
    
    def get_trades(self):
        return self.trades


class CombinedStrategy(Strategy):
    """Wrapper that runs both strategies on the same data stream"""
    
    def __init__(self, engine: fe.MatchingEngine, portfolio: fe.Portfolio, risk_engine=None):
        self.engine = engine
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        
        self.bb_strategy = BollingerBandsStrategy(engine, portfolio, risk_engine)
        self.ema_strategy = ThreeEMAStrategy(engine, portfolio, risk_engine)
        
        self.tick_count = 0
        
    def on_start(self):
        print("\n" + "=" * 60)
        print("COMBINED STRATEGY - Bollinger Bands + 3EMA/ATR")
        print("=" * 60 + "\n")
        self.bb_strategy.on_start()
        print()
        self.ema_strategy.on_start()
    
    def on_tick(self, tick):
        self.tick_count += 1
        
        if self.tick_count % 50000 == 0:
            print(f"[Combined] Processed {self.tick_count} ticks, Price: ${tick.price:.2f}")
        
        self.bb_strategy.on_tick(tick)
        self.ema_strategy.on_tick(tick)
    
    def on_fill(self, fill):
        self.bb_strategy.on_fill(fill)
        self.ema_strategy.on_fill(fill)
    
    def on_bar(self, bar):
        pass
    
    def on_end(self):
        print("\n" + "=" * 60)
        print("COMBINED STRATEGY COMPLETE")
        print("=" * 60)
        self.bb_strategy.on_end()
        self.ema_strategy.on_end()
    
    def get_trades(self):
        all_trades = []
        all_trades.extend(self.bb_strategy.get_trades())
        all_trades.extend(self.ema_strategy.get_trades())
        return sorted(all_trades, key=lambda t: t.get('timestamp', 0))
    
    def get_stats(self):
        return {
            'bb': {
                'total_trades': self.bb_strategy.total_trades,
                'winning_trades': self.bb_strategy.winning_trades
            },
            'ema': {
                'total_trades': self.ema_strategy.total_trades,
                'winning_trades': self.ema_strategy.winning_trades
            }
        }


def calculate_metrics(equity_curve, initial_capital, trades):
    import numpy as np
    
    if len(equity_curve) < 2:
        return {
            'sharpe': 0.0, 'sortino': 0.0, 'max_dd': 0.0, 'cagr': 0.0,
            'win_rate': 0.0, 'avg_win': 0.0, 'avg_loss': 0.0, 'profit_factor': 0.0,
            'total_trades': 0
        }
    
    equity = np.array(equity_curve)
    returns = np.diff(equity) / equity[:-1]
    
    if len(returns) > 0 and np.std(returns) > 0:
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 * 390)
    else:
        sharpe = 0.0
    
    neg_returns = returns[returns < 0]
    if len(neg_returns) > 0 and np.std(neg_returns) > 0:
        sortino = np.mean(returns) / np.std(neg_returns) * np.sqrt(252 * 390)
    else:
        sortino = 0.0
    
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak
    max_dd = np.max(drawdown) if len(drawdown) > 0 else 0.0
    
    if len(equity) > 1 and equity[0] > 0:
        years = len(equity) / (252 * 390)
        if years > 0:
            cagr = (equity[-1] / equity[0]) ** (1 / years) - 1
        else:
            cagr = 0.0
    else:
        cagr = 0.0
    
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
    data_file = "data/processed/btcusdt.bin"
    
    if not os.path.exists(data_file):
        print(f"Data file not found: {data_file}")
        print("Run: python3 scripts/load_datasets.py --sample --output data/processed/reliance.bin")
        return
    
    os.makedirs("results/combined_backtest", exist_ok=True)
    
    # Read first and last timestamps from binary file
    with open(data_file, 'rb') as f:
        data = f.read(40)
        first_ts = struct.unpack('<Q', data[:8])[0]
        f.seek(-40, 2)
        data = f.read(40)
        last_ts = struct.unpack('<Q', data[:8])[0]
    
    stream = fe.DataStream()
    stream.load(data_file)
    print(f"Loaded {data_file} with {stream.size()} ticks")
    
    if stream.size() == 0:
        print("[ERROR] No data loaded!")
        return
    
    initial_capital = 100000.0
    
    slippage = fe.SlippageConfig()
    slippage.fixed_bps = 2.0
    
    latency = fe.LatencyConfig()
    latency.strategy_latency_ns = 1000
    latency.engine_latency_ns = 500
    
    engine = fe.MatchingEngine(slippage)
    engine.set_latency_config(latency)
    
    portfolio = fe.Portfolio(initial_capital)
    
    risk_limits = fe.RiskLimits()
    risk_limits.max_drawdown = 0.25
    risk_limits.max_position_size = 2000
    risk_limits.max_order_size = 1000
    risk_limits.max_notional = 200000.0
    risk_limits.max_daily_loss = 10000.0
    risk_engine = fe.RiskEngine(risk_limits)
    
    print(f"\nInitial Capital: ${initial_capital:,.2f}")
    print(f"Slippage: {slippage.fixed_bps} bps")
    print(f"Latency: {latency.strategy_latency_ns + latency.engine_latency_ns} ns")
    
    strategy = CombinedStrategy(engine, portfolio, risk_engine)
    
    event_loop = fe.EventLoop()
    event_loop.set_matching_engine(engine)
    event_loop.set_portfolio(portfolio)
    event_loop.set_risk_engine(risk_engine)
    
    event_loop.run(stream, strategy, engine, portfolio)
    
    final_equity = portfolio.equity()
    total_pnl = final_equity - initial_capital
    total_return = (total_pnl / initial_capital) * 100
    
    equity_curve = portfolio.get_equity_values()
    trades = strategy.get_trades()
    stats = strategy.get_stats()
    
    metrics = calculate_metrics(equity_curve, initial_capital, trades)
    
    # Calculate duration from tick data
    duration_ns = last_ts - first_ts
    duration_days = duration_ns / (1e9 * 86400)
    duration_years = duration_days / 365.0
    
    # Convert to readable dates
    start_date = datetime.utcfromtimestamp(first_ts / 1e9).strftime('%Y-%m-%d')
    end_date = datetime.utcfromtimestamp(last_ts / 1e9).strftime('%Y-%m-%d')
    
    print("\n" + "=" * 60)
    print("COMBINED BACKTEST RESULTS")
    print("=" * 60)
    print(f"Period:             {start_date} to {end_date}")
    print(f"Duration:           {duration_days:.0f} days ({duration_years:.1f} years)")
    print(f"Initial Capital:    ${initial_capital:,.2f}")
    print(f"Final Equity:       ${final_equity:,.2f}")
    print(f"Total P&L:          ${'+' if total_pnl >= 0 else ''}{total_pnl:,.2f} ({total_return:+.2f}%)")
    print("-" * 60)
    print("STRATEGY BREAKDOWN:")
    print(f"  Bollinger Bands:  {stats['bb']['total_trades']} trades, {stats['bb']['winning_trades']} wins")
    print(f"  3EMA + ATR:       {stats['ema']['total_trades']} trades, {stats['ema']['winning_trades']} wins")
    print("-" * 60)
    print(f"Sharpe Ratio:       {metrics['sharpe']:.2f}")
    print(f"Sortino Ratio:      {metrics['sortino']:.2f}")
    print(f"Max Drawdown:       {metrics['max_dd']*100:.2f}%")
    print(f"CAGR:               {metrics['cagr']*100:.2f}%")
    print("-" * 60)
    print(f"Total Trades:       {metrics['total_trades']}")
    print(f"Win Rate:           {metrics['win_rate']*100:.1f}%")
    print(f"Avg Win:            ${metrics['avg_win']:,.2f}")
    print(f"Avg Loss:           ${metrics['avg_loss']:,.2f}")
    print(f"Profit Factor:      {metrics['profit_factor']:.2f}")
    print("=" * 60)
    
    results_data = {
        'initial_capital': initial_capital,
        'final_equity': final_equity,
        'total_pnl': total_pnl,
        'total_return_pct': total_return,
        'start_date': start_date,
        'end_date': end_date,
        'duration_days': duration_days,
        'duration_years': duration_years,
        'strategy_stats': stats,
        'metrics': metrics,
        'num_ticks': stream.size(),
        'timestamp': datetime.now().isoformat()
    }
    
    with open("results/combined_backtest/combined_results.json", "w") as f:
        json.dump(results_data, f, indent=2)
    print("\nResults exported to results/combined_backtest/combined_results.json")
    
    if trades:
        with open("results/combined_backtest/combined_trades.json", "w") as f:
            json.dump(trades, f, indent=2, default=str)
        print("Trades exported to results/combined_backtest/combined_trades.json")
        
        bb_trades = [t for t in trades if t.get('strategy') == 'BB']
        ema_trades = [t for t in trades if t.get('strategy') == '3EMA']
        
        if bb_trades:
            with open("results/combined_backtest/bb_trades.json", "w") as f:
                json.dump(bb_trades, f, indent=2, default=str)
        if ema_trades:
            with open("results/combined_backtest/ema_trades.json", "w") as f:
                json.dump(ema_trades, f, indent=2, default=str)
    
    print(f"\n[Stats] Ticks: {event_loop.ticks_processed()}, Orders: {event_loop.orders_processed()}, Fills: {event_loop.fills_generated()}")


if __name__ == "__main__":
    main()