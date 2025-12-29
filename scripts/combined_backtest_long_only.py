import os
import sys
import json
import struct
from collections import deque
from datetime import datetime
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "python"))

import felix_engine as fe
from felix.strategy.base import Strategy
from dashboard_exporter import DashboardExporter

# ==========================================
# CONFIGURATION
# ==========================================
S1_LENGTH = 20
S1_MULT = 2.5
S1_PCT_EQUITY = 0.5
S1_DIRECTION = 1

S2_SLOW_EMA_LEN = 30
S2_MID_EMA_LEN = 12
S2_FAST_EMA_LEN = 7
S2_ATR_LEN = 7
S2_TP_ATR_MULT = 4
S2_SL_ATR_MULT = 1
S2_PCT_EQUITY = 0.1

BAR_INTERVAL_MIN = 45

class Struct:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

class BarAggregator:
    def __init__(self, interval_minutes):
        self.interval_minutes = interval_minutes
        self.current_bar = None
        self.last_period_index = -1
        
    def on_tick(self, tick):
        ts_seconds = tick.timestamp / 1e9
        minutes_total = int(ts_seconds // 60)
        period_index = minutes_total // self.interval_minutes
        
        completed_bar = None
        
        if period_index > self.last_period_index:
            if self.last_period_index != -1 and self.current_bar:
                # Close the previous bar
                completed_bar = self.current_bar
            
            # Start new bar
            self.current_bar = Struct(
                timestamp=tick.timestamp,
                open=tick.price,
                high=tick.price,
                low=tick.price,
                close=tick.price,
                volume=0 
            )
            self.last_period_index = period_index
        else:
            # Update current bar
            if self.current_bar:
                self.current_bar.high = max(self.current_bar.high, tick.price)
                self.current_bar.low = min(self.current_bar.low, tick.price)
                self.current_bar.close = tick.price
        
        return completed_bar

class BollingerBandsStrategy:
    """Strategy 1: Bollinger Bands (For Long + Short)"""
    def __init__(self, engine, portfolio, context=None):
        self.engine = engine
        self.portfolio = portfolio
        self.context = context
        self.length = S1_LENGTH
        self.mult = S1_MULT
        self.pct_equity = S1_PCT_EQUITY
        
        self.history = deque(maxlen=self.length + 1) # Store Close prices
        self.history_lower = deque(maxlen=2)
        self.history_upper = deque(maxlen=2)
        
        self.position = 0      # Current signed size
        self.entry_price = 0.0
        
        self.pending_long = False
        self.pending_short = False
        self.entry_stop_price = 0.0
        self.entry_ts = 0
        
        self.trades = []
        self.stats = {'total_trades': 0, 'wins': 0}
        
        self.total_volume = 0.0
        self.fill_count = 0
        self.total_commission = 0.0
        self.current_net_equity = portfolio.equity()
        
    def on_bar(self, bar):
        # Update History
        self.history.append(bar.close)
        
        if len(self.history) < self.length:
            return

        # Calculate Indicators
        prices = list(self.history)[-self.length:]
        sma = sum(prices) / self.length
        variance = sum((p - sma) ** 2 for p in prices) / self.length
        std = variance ** 0.5
        
        upper = sma + (self.mult * std)
        lower = sma - (self.mult * std)
        
        # history for signal logic (prev vs current)
        self.history_upper.append(upper)
        self.history_lower.append(lower)
        
        if len(self.history_upper) < 2:
            return
            
        current_close = bar.close
        prev_close = prices[-2]
        
        current_lower = lower
        prev_lower = self.history_lower[-2]
        
        current_upper = upper
        prev_upper = self.history_upper[-2]
        
        long_signal = (prev_close < prev_lower) and (current_close > current_lower)
        short_signal = (prev_close >= prev_upper) and (current_close < current_upper)
        
        if self.context:
             pass

        allow_long = (S1_DIRECTION == 0) or (S1_DIRECTION == 1)
        allow_short = (S1_DIRECTION == 0) or (S1_DIRECTION == -1)
        
        # Long Entry
        if allow_long and long_signal:
             self.entry_stop_price = current_lower
             self.pending_long = True
        else:
             self.pending_long = False
             
        # Short Entry
        if allow_short and short_signal:
             self.entry_stop_price = current_upper
             self.pending_short = True
        else:
             self.pending_short = False
        
        # Exits
        if self.position > 0 and short_signal:
             self._close_position(bar, "BB Upper Cross")
             
        elif self.position < 0 and long_signal:
             self._close_position(bar, "BB Lower Cross")

        
    def on_tick(self, tick):
        # Long Entry Execution
        if self.pending_long and self.position == 0:
            if tick.price >= self.entry_stop_price:
                 self._open_position(tick, 1)
                 self.pending_long = False
        
        # Short Entry Execution
        if self.pending_short and self.position == 0:
            if tick.price <= self.entry_stop_price:
                 self._open_position(tick, -1)
                 self.pending_short = False

    def _open_position(self, tick, side):
        if self.position != 0: return
        
        if self.context:
            equity = self.context.current_net_equity
        else:
            equity = self.portfolio.equity()
            
        if equity <= 0: return

        # Calc Size
        alloc_equity = equity * self.pct_equity
        size = alloc_equity / tick.price
        if size <= 0: return
        
        size = min(size, 1000.0)

        self.position = size * side
        self.entry_price = tick.price
        
        order = fe.Order()
        order.symbol_id = 1
        order.side = fe.Side.BUY if side == 1 else fe.Side.SELL
        order.order_type = fe.OrderType.MARKET
        order.size = size
        order.price = tick.price
        order.timestamp = tick.timestamp
        
        self.engine.submit_order(order)
        
        # Log Entry
        if self.context:
            self.context.log_trade({
                'timestamp': tick.timestamp,
                'strategy': 'BB',
                'type': 'entry',
                'size': size * side,
                'price': tick.price
            })
            self.entry_ts = tick.timestamp

    def _close_position(self, bar, reason):
        self.engine.submit_order(order)
        # self.position is reset to 0 AFTER this in original logs, but here we read it before reset
        
        # Calc PnL
        entry_price = self.entry_price
        exit_price = bar.close
        qty = abs(self.position)
        side = 1 if self.position > 0 else -1
        
        # Approximate PnL (Gross)
        pnl = (exit_price - entry_price) * qty * side
        # Net PnL (deduct comms 0.04% total)
        comm = (entry_price * qty * 0.0002) + (exit_price * qty * 0.0002)
        net_pnl = pnl - comm
        
        if self.context:
            self.context.log_trade({
                'timestamp': bar.timestamp,
                'strategy': 'BB',
                'type': 'exit',
                'size': qty * side * -1, # Exit size
                'price': exit_price,
                'pnl': net_pnl
            })
            
        self.position = 0

class ThreeEMAStrategy:
    def __init__(self, engine, portfolio, context=None):
        # ... existing ...
        self.context = context
        self.entry_ts = 0

    def _open_position(self, bar):
        self.engine.submit_order(order)
        
        if self.context:
             self.context.log_trade({
                'timestamp': bar.timestamp,
                'strategy': '3EMA',
                'type': 'entry',
                'size': size,
                'price': bar.close
            })
             self.entry_ts = bar.timestamp

    def _close_position(self, tick_or_bar, reason):
        price = getattr(tick_or_bar, 'price', getattr(tick_or_bar, 'close', 0))
        ts = getattr(tick_or_bar, 'timestamp', 0)
        
        # Calc PnL
        entry_price = self.entry_price
        exit_price = price
        qty = self.position
        
        pnl = (exit_price - entry_price) * qty # Long only
        comm = (entry_price * qty * 0.0002) + (exit_price * qty * 0.0002)
        net_pnl = pnl - comm
        
        if self.context:
            self.context.log_trade({
                'timestamp': ts,
                'strategy': '3EMA',
                'type': 'exit',
                'size': -qty,
                'price': exit_price,
                'pnl': net_pnl
            })

        self.engine.submit_order(order)
        self.position = 0

class CombinedStrategy(Strategy):
    def __init__(self, engine, portfolio):
        self.bb = BollingerBandsStrategy(engine, portfolio, context=self)
        self.ema = ThreeEMAStrategy(engine, portfolio, context=self)
        
        self.trades_list = []
        self.equity_curve = []
        self.last_equity_day = -1
        
    def log_trade(self, trade_dict):
        self.trades_list.append(trade_dict)

    def on_tick(self, tick):
        ts_sec = tick.timestamp / 1e9
        day_idx = int(ts_sec // 86400)
        
        if day_idx > self.last_equity_day:
            # Fill gaps if any?
            if self.last_equity_day != -1:
                # If we skipped days (no ticks), we might need to fill.
                # But for BTC 1m, gaps are rare.
                pass
                
            self.equity_curve.append(self.current_net_equity)
            self.last_equity_day = day_idx

# CONFIGURATION
# ==========================================
S1_LENGTH = 20
S1_MULT = 2.5
S1_PCT_EQUITY = 0.5
S1_DIRECTION = 1

S2_SLOW_EMA_LEN = 30
S2_MID_EMA_LEN = 12
S2_FAST_EMA_LEN = 7
S2_ATR_LEN = 7
S2_TP_ATR_MULT = 4
S2_SL_ATR_MULT = 1
S2_PCT_EQUITY = 0.1

BAR_INTERVAL_MIN = 45


class Struct:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

class BarAggregator:
    """Aggregates 1-min ticks into N-min bars"""
    def __init__(self, interval_minutes):
        self.interval_minutes = interval_minutes
        self.current_bar = None
        self.last_period_index = -1
        
    def on_tick(self, tick):
        ts_seconds = tick.timestamp / 1e9
        minutes_total = int(ts_seconds // 60)
        period_index = minutes_total // self.interval_minutes
        
        completed_bar = None
        
        # If new period detected
        if period_index > self.last_period_index:
            if self.last_period_index != -1 and self.current_bar:
                # Close the previous bar
                completed_bar = self.current_bar
            
            # Start new bar
            self.current_bar = Struct(
                timestamp=tick.timestamp,
                open=tick.price,
                high=tick.price,
                low=tick.price,
                close=tick.price,
                volume=0 
            )
            
            self.last_period_index = period_index

        else:
            # Update current bar
            if self.current_bar:
                self.current_bar.high = max(self.current_bar.high, tick.price)
                self.current_bar.low = min(self.current_bar.low, tick.price)
                self.current_bar.close = tick.price
                # self.current_bar.volume += tick.volume
        
        return completed_bar

class BollingerBandsStrategy:
    """Strategy 1: Bollinger Bands (Long + Short)"""
    def __init__(self, engine, portfolio, context=None):
        self.engine = engine
        self.portfolio = portfolio
        self.context = context
        self.length = S1_LENGTH
        self.mult = S1_MULT
        self.pct_equity = S1_PCT_EQUITY
        
        self.history = deque(maxlen=self.length + 1) # Store Close prices
        self.history_lower = deque(maxlen=2)
        self.history_upper = deque(maxlen=2)
        
        self.position = 0      # Current signed size
        self.entry_price = 0.0
        
        self.pending_long = False
        self.pending_short = False
        self.entry_stop_price = 0.0
        
        self.trades = []
        self.stats = {'total_trades': 0, 'wins': 0}
        
        self.total_volume = 0.0
        self.fill_count = 0
        self.total_commission = 0.0
        self.current_net_equity = portfolio.equity()
        
    def on_bar(self, bar):
        # Update History
        self.history.append(bar.close)
        
        if len(self.history) < self.length:
            return

        # Calculate Indicators
        prices = list(self.history)[-self.length:]
        sma = sum(prices) / self.length
        variance = sum((p - sma) ** 2 for p in prices) / self.length
        std = variance ** 0.5
        
        upper = sma + (self.mult * std)
        lower = sma - (self.mult * std)
        
        # history for signal logic (prev vs current)
        self.history_upper.append(upper)
        self.history_lower.append(lower)
        
        if len(self.history_upper) < 2:
            return
        
        current_close = bar.close
        prev_close = prices[-2]
        
        current_lower = lower
        prev_lower = self.history_lower[-2]
        
        current_upper = upper
        prev_upper = self.history_upper[-2]
        
        long_signal = (prev_close < prev_lower) and (current_close > current_lower)
        short_signal = (prev_close > prev_upper) and (current_close < current_upper)
        
        prev_close = prices[-2]
        prev_lower = self.history_lower[-2]
        current_lower = lower
        
        prev_upper = self.history_upper[-2]
        current_upper = upper
        
        # Signal Generation (at Close of Bar T)
        # Long Entry: Cross Over Lower Band
        long_signal = (prev_close < prev_lower) and (current_close > current_lower)
        
        # Short Signal (for Exit): Prev >= Upper and Curr < Upper.
        short_signal = (prev_close >= prev_upper) and (current_close < current_upper)
        
        if self.context:
             pass

        allow_long = (S1_DIRECTION == 0) or (S1_DIRECTION == 1)
        allow_short = (S1_DIRECTION == 0) or (S1_DIRECTION == -1)
        
        # Long Entry
        if allow_long and long_signal:
             # print(f"[BB] Signal LONG at {bar.timestamp}")
             self.entry_stop_price = current_lower
             self.pending_long = True
        else:
             self.pending_long = False
             
        # Short Entry
        if allow_short and short_signal:
             self.entry_stop_price = current_upper
             self.pending_short = True
        else:
             self.pending_short = False
        
        # Exits
        if self.position > 0 and short_signal:
             # Exit Long
             self._close_position(bar, "BB Upper Cross")
             
        elif self.position < 0 and long_signal:
             # Exit Short
             self._close_position(bar, "BB Lower Cross")

        
    def on_tick(self, tick):
        # Long Entry Execution
        if self.pending_long and self.position == 0:
            if tick.price >= self.entry_stop_price:
                 self._open_position(tick, 1)
                 self.pending_long = False
        
        # Short Entry Execution
        if self.pending_short and self.position == 0:
            if tick.price <= self.entry_stop_price:
                 self._open_position(tick, -1)
                 self.pending_short = False

    def _open_position(self, tick, side):
        if self.position != 0: return
        
        if self.context:
            equity = self.context.current_net_equity
        else:
            equity = self.portfolio.equity()
            
        if equity <= 0: return

        # Calc Size
        alloc_equity = equity * self.pct_equity
        size = alloc_equity / tick.price
        if size <= 0: return
        
        size = min(size, 1000.0)

        self.position = size * side
        self.entry_price = tick.price
        
        order = fe.Order()
        order.symbol_id = 1
        order.side = fe.Side.BUY if side == 1 else fe.Side.SELL
        order.order_type = fe.OrderType.MARKET
        order.size = size
        order.price = tick.price
        order.timestamp = tick.timestamp
        
        self.engine.submit_order(order)
        
        # LOGGING
        if self.context:
            self.context.log_trade({
                'timestamp': tick.timestamp,
                'strategy': 'BB',
                'type': 'entry',
                'size': size * side,
                'price': tick.price
            })

    def _close_position(self, bar, reason):
        if self.position == 0: return
        
        size = abs(self.position)
        side = fe.Side.SELL if self.position > 0 else fe.Side.BUY
        
        # Calc PnL
        entry_price = self.entry_price
        exit_price = bar.close
        qty = size
        pos_side = 1 if self.position > 0 else -1
        
        pnl = (exit_price - entry_price) * qty * pos_side
        
        # Costs
        # Commission: 0.04% round trip (0.02% per side)
        comm = (entry_price * qty * 0.0002) + (exit_price * qty * 0.0002)
        # Slippage: 2bps per side (estimated here)
        slip = (entry_price * qty * 0.0002) + (exit_price * qty * 0.0002)
        
        net_pnl = pnl - comm - slip
        
        if self.context:
            self.context.log_trade({
                'timestamp': bar.timestamp,
                'strategy': 'BB',
                'type': 'exit',
                'size': qty * pos_side * -1,
                'price': exit_price,
                'pnl': net_pnl
            })
        
        order = fe.Order()
        order.symbol_id = 1
        order.side = side
        order.order_type = fe.OrderType.MARKET
        order.size = size
        order.price = bar.close
        order.timestamp = bar.timestamp
        
        self.engine.submit_order(order)
        self.position = 0
        print(f"[BB] CLOSE {size} @ {bar.close:.2f} ({reason})")

    def on_fill(self, fill):
        pass 

class ThreeEMAStrategy:
    """Strategy 2: 3EMA + ATR"""
    def __init__(self, engine, portfolio, context=None):
        self.engine = engine
        self.portfolio = portfolio
        self.context = context
        
        self.slow_len = S2_SLOW_EMA_LEN
        self.mid_len = S2_MID_EMA_LEN
        self.fast_len = S2_FAST_EMA_LEN
        self.atr_len = S2_ATR_LEN
        
        self.ema_fast = 0.0
        self.ema_mid = 0.0
        self.ema_slow = 0.0
        
        self.history_ema_mid = deque(maxlen=2)
        self.history_ema_slow = deque(maxlen=2)
        self.history_ema_fast = deque(maxlen=2)
        
        self.tr_history = deque(maxlen=self.atr_len * 2) 
        self.prev_close = 0.0
        self.atr = 0.0
        
        self.position = 0 # Long only: 0 or >0
        self.entry_price = 0.0
        self.tp_price = 0.0
        self.sl_price = 0.0
        
        self.stats = {'total_trades': 0, 'wins': 0}

    def _calc_ema(self, price, prev_ema, length):
        if prev_ema == 0.0: return price
        alpha = 2 / (length + 1)
        return (price - prev_ema) * alpha + prev_ema

    def _calc_rma(self, series, length):
        if not series: return 0.0
        val = series[-1]
        return 0.0

    def on_bar(self, bar):
        # Update Indicators
        self.ema_fast = self._calc_ema(bar.close, self.ema_fast, self.fast_len)
        self.ema_mid = self._calc_ema(bar.close, self.ema_mid, self.mid_len)
        self.ema_slow = self._calc_ema(bar.close, self.ema_slow, self.slow_len)
        
        self.history_ema_fast.append(self.ema_fast)
        self.history_ema_mid.append(self.ema_mid)
        self.history_ema_slow.append(self.ema_slow)
        
        # ATR Calculation
        if self.prev_close > 0:
            tr = max(bar.high - bar.low, 
                     abs(bar.high - self.prev_close), 
                     abs(bar.low - self.prev_close))
        else:
            tr = bar.high - bar.low
        
        self.prev_close = bar.close
        
        # Initialize ATR
        if self.atr == 0:
            self.atr = tr
        else:
            alpha = 1.0 / self.atr_len
            self.atr = (tr * alpha) + (self.atr * (1 - alpha))
            
        if len(self.history_ema_slow) < 2: return

        # Logic -
        # Entry: Mid crosses above Slow
        # Exit: Fast crosses below Mid
        
        curr_mid = self.ema_mid
        prev_mid = self.history_ema_mid[-2]
        
        curr_slow = self.ema_slow
        prev_slow = self.history_ema_slow[-2]
        
        curr_fast = self.ema_fast
        prev_fast = self.history_ema_fast[-2]
        
        entry_signal = (prev_mid <= prev_slow) and (curr_mid > curr_slow)
        exit_signal = (prev_fast >= prev_mid) and (curr_fast < curr_mid)
        
        # Execution
        if self.position > 0:
            # Check Exit Signal
            if exit_signal:
                self._close_position(bar, "EMA Cross")
        elif self.position == 0:
            if entry_signal:
                self._open_position(bar)

    def on_tick(self, tick):
        # Check TP/SL intra-bar if possible
        if self.position > 0:
            if tick.price <= self.sl_price:
                self._close_position(tick, "Stop Loss")
            elif tick.price >= self.tp_price:
                self._close_position(tick, "Take Profit")

    def _open_position(self, bar):
        if self.context:
            equity = self.context.current_net_equity
        else:
            equity = self.portfolio.equity()
            
        if equity <= 0: return # Bankrupt
        
        alloc_equity = equity * S2_PCT_EQUITY
        size = alloc_equity / bar.close
        if size <= 0: return
        size = min(size, 1000.0)
        
        self.position = size
        self.entry_price = bar.close
        self.entry_ts = bar.timestamp
        self.tp_price = bar.close + (self.atr * S2_TP_ATR_MULT)
        self.sl_price = bar.close - (self.atr * S2_SL_ATR_MULT)
        
        order = fe.Order()
        order.symbol_id = 1
        order.side = fe.Side.BUY
        order.order_type = fe.OrderType.MARKET
        order.size = size
        order.price = bar.close
        order.timestamp = bar.timestamp
        self.engine.submit_order(order)
        
        if self.context:
            self.context.log_trade({
                'timestamp': bar.timestamp,
                'strategy': '3EMA',
                'type': 'entry',
                'size': size,
                'price': bar.close
            })
            
        print(f"[3EMA] BUY {size} @ {bar.close:.2f} (TP:{self.tp_price:.2f}, SL:{self.sl_price:.2f})")

    def _close_position(self, tick_or_bar, reason):
        if self.position == 0: return
        
        size = self.position
        price = getattr(tick_or_bar, 'price', getattr(tick_or_bar, 'close', 0))
        ts = getattr(tick_or_bar, 'timestamp', 0)
        
        # Calc PnL
        entry_price = self.entry_price
        exit_price = price
        qty = size
        
        pnl = (exit_price - entry_price) * qty
        
        # Costs
        comm = (entry_price * qty * 0.0002) + (exit_price * qty * 0.0002) # Comm 2bps/side
        slip = (entry_price * qty * 0.0002) + (exit_price * qty * 0.0002) # Slip 2bps/side
        
        net_pnl = pnl - comm - slip
        
        if self.context:
            self.context.log_trade({
                'timestamp': ts,
                'strategy': '3EMA',
                'type': 'exit',
                'size': -qty,
                'price': exit_price,
                'pnl': net_pnl
            })
        
        order = fe.Order()
        order.symbol_id = 1
        order.side = fe.Side.SELL
        order.order_type = fe.OrderType.MARKET
        order.size = size
        order.price = price
        order.timestamp = ts
        
        self.engine.submit_order(order)
        self.position = 0
        print(f"[3EMA] SELL {size} @ {price:.2f} ({reason})")


class CombinedStrategy(Strategy):
    def __init__(self, engine, portfolio):
        self.engine = engine
        self.portfolio = portfolio
        self.aggregator = BarAggregator(BAR_INTERVAL_MIN)
        self.total_volume = 0.0
        self.fill_count = 0
        self.total_commission = 0.0
        self.current_net_equity = portfolio.equity()
        
        self.trades_list = []
        self.equity_curve = []
        self.last_equity_day = -1

        self.bb = BollingerBandsStrategy(engine, portfolio, context=self)
        self.ema = ThreeEMAStrategy(engine, portfolio, context=self)
        
        self.total_volume = 0.0
        self.fill_count = 0
        self.total_commission = 0.0
        self.current_net_equity = portfolio.equity()
        
        # We need to route fills to the correct strategy.
        # WHat we'll do: divide fills by looking at position count? 
        # Or just let them track their own 'expected' position.
        
    def log_trade(self, trade_dict):
        self.trades_list.append(trade_dict)
        
    def check_daily_equity(self, timestamp):
        # Timestamp is ns.
        ts_sec = timestamp / 1e9
        day_idx = int(ts_sec // 86400)
        
        if day_idx > self.last_equity_day:
            if self.last_equity_day != -1:
                # Capture end of previous day? Or just current state.
                # Current state is fine.
                self.equity_curve.append(self.current_net_equity)
            else:
                 # First day
                 self.equity_curve.append(self.current_net_equity)
                 
            self.last_equity_day = day_idx

    def on_start(self):
        print("Starting Combined Strategy (Binary Version)...")
        
    def on_tick(self, tick):
        self.last_price = tick.price
        
        self.check_daily_equity(tick.timestamp)

        bar = self.aggregator.on_tick(tick)
        
        # Run Intra-bar logic (TP/SL for EMA, Pending Entry for BB)
        self.ema.on_tick(tick)
        self.bb.on_tick(tick)
        
        # Run Bar logic if new bar
        if bar:
            self.bb.on_bar(bar)
            self.ema.on_bar(bar)
            
    def on_bar(self, bar):
        pass

    def on_fill(self, fill):
        # Track Volume and Commission
        qty = getattr(fill, 'volume', 0)
        price = getattr(fill, 'price', 0)
        
        # 0.04% commission per fill (approx round trip 0.04% means 0.02% per side)
        comm = price * qty * 0.0002 
        
        self.total_volume += price * qty
        self.total_commission += comm
        self.fill_count += 1
        
        # Determine Current Net Equity
        # Portfolio Equity (Gross) - Total Commission
        self.current_net_equity = self.portfolio.equity() - self.total_commission
        
    def on_end(self):
        print("Backtest Complete. Closing any open positions for reporting...")
        
        # Force close BB
        if self.bb.position != 0:
            self._force_close_log(self.bb, "BB")
            
        # Force close EMA
        if self.ema.position != 0:
            self._force_close_log(self.ema, "3EMA")
            
    def _force_close_log(self, strategy_instance, name):
        qty = abs(strategy_instance.position)
        side = 1 if strategy_instance.position > 0 else -1
        entry = strategy_instance.entry_price
        exit_px = self.last_price
        
        pnl = (exit_px - entry) * qty * side
        comm = (entry * qty * 0.0002) + (exit_px * qty * 0.0002)
        slip = (entry * qty * 0.0002) + (exit_px * qty * 0.0002)
        net_pnl = pnl - comm - slip
        
        print(f"[{name}] FORCE CLOSE {qty:.4f} @ {exit_px:.2f} (PnL: ${net_pnl:.2f})")
        
        self.log_trade({
            'timestamp': 0, # Use 0 or max to signify end
            'strategy': name,
            'type': 'exit',
            'size': -strategy_instance.position,
            'price': exit_px,
            'pnl': net_pnl
        })


def calculate_and_print_returns(equity_curve, initial_capital, start_date_str='2021-01-01', final_net_liq=None):
    """ It Calculates Year-on-Year and Quarterly returns from daily equity curve."""
    if not equity_curve:
        print("No equity curve data to analyze.")
        return

    try:
        # Create DataFrame
        dates = [pd.Timestamp(start_date_str) + timedelta(days=i) for i in range(len(equity_curve))]
        
        if final_net_liq is not None:
             equity_curve[-1] = final_net_liq
             
        df = pd.DataFrame({'equity': equity_curve}, index=dates)
        
        # Resample to Yearly and Quarterly
        yearly = df['equity'].resample('Y').last()
        quarterly = df['equity'].resample('Q').last()
        
        # Calculate Returns
        # We need the starting equity for the very first period.
        # Shift the series to get the previous period's close. 
        # For the first period, use initial_capital.
        
        print("\n" + "="*40)
        print(" PERIODIC RETURNS ANALYSIS")
        print("="*40)
        
        # --- YEARLY ---
        print("\n[ YEAR-ON-YEAR RETURNS ]")
        print(f"{'Year':<10} | {'Start Equity':<15} | {'End Equity':<15} | {'Return':<10}")
        print("-" * 58)
        
        y_start = initial_capital
        for date, y_end in yearly.items():
            ret = ((y_end - y_start) / y_start) * 100
            print(f"{date.year:<10} | ${y_start:<14,.2f} | ${y_end:<14,.2f} | {ret:>6.2f}%")
            y_start = y_end # Next year starts with this year's end

        # --- QUARTERLY ---
        print("\n[ QUARTERLY RETURNS ]")
        print(f"{'Period':<15} | {'Start Equity':<15} | {'End Equity':<15} | {'Return':<10}")
        print("-" * 63)
        
        q_start = initial_capital
        for date, q_end in quarterly.items():
            ret = ((q_end - q_start) / q_start) * 100
            quarter_str = f"{date.year}-Q{date.quarter}"
            print(f"{quarter_str:<15} | ${q_start:<14,.2f} | ${q_end:<14,.2f} | {ret:>6.2f}%")
            q_start = q_end

        # Save to file
        with open("returns_breakdown.txt", "w") as f:
            f.write("PERIODIC RETURNS ANALYSIS\n")
            f.write("=========================\n\n")
            
            f.write("[ YEAR-ON-YEAR RETURNS ]\n")
            y_start = initial_capital
            for date, y_end in yearly.items():
                ret = ((y_end - y_start) / y_start) * 100
                f.write(f"Year {date.year}: {ret:.2f}% (${y_start:.2f} -> ${y_end:.2f})\n")
                y_start = y_end
            
            f.write("\n[ QUARTERLY RETURNS ]\n")
            q_start = initial_capital
            for date, q_end in quarterly.items():
                ret = ((q_end - q_start) / q_start) * 100
                f.write(f"{date.year}-Q{date.quarter}: {ret:.2f}% (${q_start:.2f} -> ${q_end:.2f})\n")
                q_start = q_end
                
        print("\nAnalysis saved to 'returns_breakdown.txt'")

    except Exception as e:
        print(f"Error calculating returns: {e}")



def main():
    # Construct absolute path to data file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    data_file = os.path.join(project_root, "data", "processed", "btc_2021_2025.bin")
    
    if not os.path.exists(data_file):
        print(f"Error: {data_file} not found.")
        return

    # Engine Setup
    initial_capital = 100000.0
    slippage = fe.SlippageConfig()
    slippage.fixed_bps = 2.0
    
    engine = fe.MatchingEngine(slippage)
    portfolio = fe.Portfolio(initial_capital)
    
    # Run
    print(f"Loading data from {data_file}...")
    stream = fe.DataStream()
    stream.load(data_file)
    print(f"Loaded {stream.size()} ticks.")
    
    strategy = CombinedStrategy(engine, portfolio)
    
    event_loop = fe.EventLoop()
    event_loop.set_matching_engine(engine)
    event_loop.set_portfolio(portfolio)
    # event_loop.set_risk_engine(risk_engine)
    
    start_time = datetime.now()
    event_loop.run(stream, strategy, engine, portfolio)
    end_time = datetime.now()
    
    # Results
    final_equity = portfolio.equity()
    duration = (end_time - start_time).total_seconds()
    
    # Commission Calc (0.04% of Volume -> 0.02% per side)
    # total_volume tracks both sides, so we apply 0.0002 to total.
    total_volume = strategy.total_volume
    commission = total_volume * 0.0002 
    
    # GROSS EQUITY (Balance + Unrealized PnL)
    final_gross_equity = portfolio.equity()
    
    total_pnl_realized = sum(t['pnl'] for t in strategy.trades_list if 'pnl' in t)
    net_liquidating_value = initial_capital + total_pnl_realized
    
    print("\n" + "=" * 40)
    print(" RESULTS (Net Liquidating Value) ")
    print("=" * 40)
    print(f"Initial Capital:       ${initial_capital:,.2f}")
    print(f"Net Liquidating Value: ${net_liquidating_value:,.2f}")
    print(f"Total Return:          {((net_liquidating_value - initial_capital)/initial_capital)*100:.2f}%")
    print("-" * 40)
    print(f"Gross Equity (Est):    ${final_gross_equity:,.2f}")
    print(f"Commission Paid:       ${commission:,.2f}")
    print(f"Total Fills:           {strategy.fill_count}")
    print(f"Execution Time:        {duration:.2f} seconds")
    print("=" * 40)
    
    with open("results_summary.txt", "w") as f:
        f.write(f"Initial Capital: ${initial_capital:,.2f}\n")
        f.write(f"Net Liq Value:   ${net_liquidating_value:,.2f}\n")
        f.write(f"Total Return:    {((net_liquidating_value - initial_capital)/initial_capital)*100:.2f}%\n")
        f.write(f"Total Fills:     {strategy.fill_count}\n")
        
    # Analysis
    calculate_and_print_returns(strategy.equity_curve, initial_capital, final_net_liq=net_liquidating_value)

    # Export
    print("Exporting for Dashboard...")
    dashboard_path = os.path.join(project_root, "dashboard_data")
    exporter = DashboardExporter(dashboard_path)
    exporter.export(strategy.equity_curve, strategy.trades_list, initial_capital)


if __name__ == "__main__":
    main()
