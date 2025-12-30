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

CONFIG_FILE = "backtest_config.json"

class DataLoader:
    def __init__(self, config_file):
        self.config = self._load_config(config_file)
        self.symbol_specs = {}
        
    def _load_config(self, filepath):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filepath)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path, 'r') as f:
            return json.load(f)
            
    def get_symbol_spec(self, symbol_name):
        if symbol_name not in self.config['assets']:
            raise ValueError(f"Symbol {symbol_name} not defined in config")
        return self.config['assets'][symbol_name]

class OrderStatus:
    OPEN = "OPEN"
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"

class OrderManager:
    """Simulates a Real Exchange/Terminal (MT5 Style)"""
    def __init__(self, engine, portfolio, symbol_spec):
        self.engine = engine
        self.portfolio = portfolio
        self.spec = symbol_spec
        
        self.orders = [] # All orders history
        self.working_orders = [] # Active Limit/Stop orders
        self.trade_log = []
        self.open_positions = {} # strategy_id -> size
        
        self.order_id_counter = 0
        
    def submit_market_on_open(self, strategy_id, side, size_setup):
        """ Market Order: Fills at Next Open """
        return self._submit_order(strategy_id, 'MARKET_ON_OPEN', side, size_setup, price=0)

    def submit_limit(self, strategy_id, side, size_setup, limit_price):
        """ Limit Order: Fills if Price reaches Limit """
        return self._submit_order(strategy_id, 'LIMIT', side, size_setup, price=limit_price)

    def submit_stop(self, strategy_id, side, size_setup, stop_price):
        """ Stop Order: Triggers if Price passes Stop """
        return self._submit_order(strategy_id, 'STOP', side, size_setup, price=stop_price)

    def _submit_order(self, strategy_id, order_type, side, size_setup, price):
        order = {
            'id': self._next_id(),
            'strategy_id': strategy_id,
            'type': order_type,
            'side': side, 
            'size_setup': size_setup,
            'price': price, # Limit or Stop price
            'status': OrderStatus.OPEN, # Market on Open is effectively "Open" for next tick
            'created_at': -1 # Set at processing
        }
        self.orders.append(order)
        self.working_orders.append(order)
        return order['id']

        
    def process_pending_orders(self, tick):
        """
        Called on EVERY tick.
        Checks ALL working orders (Market, Limit, Stop) against current tick.
        """
        executed_orders = []
        
        # We iterate a copy because we might modify the list
        for order in self.working_orders[:]:
            if order['status'] not in [OrderStatus.OPEN, "PENDING"]: continue
            
            fill_price = None
            price = tick.price
            
            # --- MATCHING LOGIC ---
            if order['type'] == 'MARKET_ON_OPEN':
                # ALWAYS Fill at Current Price (simulating Open)
                fill_price = price
                
            elif order['type'] == 'LIMIT':
                # Limit Buy: Low <= Limit
                # Limit Sell: High >= Limit
                # Conservative: Use Tick Price.
                # If Buy, and Price <= Limit: Fill
                if order['side'] == 1 and price <= order['price']:
                    fill_price = order['price'] # Limit orders fill at Limit or Better
                # If Sell, and Price >= Limit: Fill
                elif order['side'] == -1 and price >= order['price']:
                    fill_price = order['price']
                    
            elif order['type'] == 'STOP':
                 # Stop Buy: High >= Stop (Breakout)
                 if order['side'] == 1 and price >= order['price']:
                     fill_price = price # Stop becomes Market, fill at current
                 # Stop Sell: Low <= Stop (Breakdown)
                 elif order['side'] == -1 and price <= order['price']:
                     fill_price = price

            # --- EXECUTION ---
            if fill_price is not None:
                # Slippage Calculation
                slippage_bps = self.spec['slippage_bps']
                
                # Apply Slippage ONLY to Market/Stop execution. Limit is fixed.
                if order['type'] in ['MARKET_ON_OPEN', 'STOP']:
                    if order['side'] == 1: fill_price *= (1 + slippage_bps/10000)
                    else: fill_price *= (1 - slippage_bps/10000)
                
                # Apply Tick Size
                tick_size = self.spec['tick_size']
                fill_price = round(fill_price / tick_size) * tick_size
                
                # Calculate Size
                lot_size = self.spec['lot_size']
                
                # Determine Total Order Size (if fixed) or Dynamic
                if order.get('total_size') is None:
                    if callable(order['size_setup']):
                        raw_size = order['size_setup'](fill_price)
                    else:
                        raw_size = order['size_setup']
                    order['total_size'] = (raw_size // lot_size) * lot_size
                
                remaining = order['total_size'] - order.get('filled_size', 0)
                if remaining <= 0:
                    order['status'] = OrderStatus.FILLED
                    if order in self.working_orders: self.working_orders.remove(order)
                    continue

                # SIMULATE PARTIAL FILL (Assume full fill for now, but enabled Logic)
                exec_size = remaining
                
                # Commission
                comm_bps = self.spec['commission_bps']
                comm_cost = (exec_size * fill_price) * (comm_bps/10000)
                
                # Update State
                order['filled_size'] = order.get('filled_size', 0) + exec_size
                
                # Log Trade
                trade = {
                    'id': order['id'],
                    'strategy': order['strategy_id'],
                    'timestamp': tick.timestamp,
                    'side': 'BUY' if order['side'] == 1 else 'SELL',
                    'price': fill_price,
                    'raw_price': price,
                    'size': exec_size,
                    'commission': comm_cost,
                    'slippage_bps': slippage_bps if order['type'] != 'LIMIT' else 0,
                    'type_req': order['type'],
                    'comment': 'Filled' if order['filled_size'] >= order['total_size'] else 'Partial'
                }
                self.trade_log.append(trade)
                
                # Update Position
                curr_pos = self.open_positions.get(order['strategy_id'], 0)
                self.open_positions[order['strategy_id']] = curr_pos + (exec_size * order['side'])
                
                # Update Status
                if order['filled_size'] >= order['total_size']:
                    order['status'] = OrderStatus.FILLED
                    order['fill_info'] = trade
                    executed_orders.append(order)
                    self.working_orders.remove(order)
                else:
                    order['status'] = "PARTIALLY_FILLED"
                    # Remains in working_orders
                
                # Engine Sync
                fe_order = fe.Order()
                fe_order.symbol_id = self.spec['symbol_id']
                fe_order.side = fe.Side.BUY if order['side'] == 1 else fe.Side.SELL
                fe_order.order_type = fe.OrderType.MARKET # FE only sees filled market trades
                fe_order.size = exec_size
                fe_order.price = fill_price
                fe_order.timestamp = tick.timestamp
                self.engine.submit_order(fe_order)
            
        return executed_orders

    def cancel_order(self, order_id):
        """ Cancels a working order if it exists and is open """
        for order in self.working_orders:
            if order['id'] == order_id:
                if order['status'] in [OrderStatus.OPEN, "PENDING"]:
                    order['status'] = OrderStatus.CANCELED
                    self.working_orders.remove(order)
                    return True
        return False

    def modify_order(self, order_id, new_price=None, new_size_setup=None):
        """ Modifies price or size of an existing working order """
        for order in self.working_orders:
            if order['id'] == order_id:
                if order['status'] in [OrderStatus.OPEN, "PENDING"]:
                    if new_price is not None:
                        order['price'] = new_price
                    if new_size_setup is not None:
                        order['size_setup'] = new_size_setup
                    return True
        return False

    def _next_id(self):
        self.order_id_counter += 1
        return self.order_id_counter

# CONFIGURATION (Strategy Params)
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
        
        return completed_bar


class BollingerBandsStrategy:
    """Strategy 1: Bollinger Bands (For Long + Short)"""
    def __init__(self, manager, name="BB"):
        self.manager = manager
        self.name = name
        self.length = S1_LENGTH
        self.mult = S1_MULT
        self.pct_equity = S1_PCT_EQUITY
        
        self.history = deque(maxlen=self.length + 1)
        self.history_lower = deque(maxlen=2)
        self.history_upper = deque(maxlen=2)
        
        self.entry_fill_price = 0.0 # Track actual entry
        self.position_size = 0.0 # Track signed size
        
    def on_fill(self, trade):
        # Callback from Manager when order fills
        if trade['strategy'] != self.name: return
        
        prev_size = self.position_size
        size_signed = trade['size'] if trade['side'] == 'BUY' else -trade['size']
        self.position_size += size_signed
        
        if abs(self.position_size) > abs(prev_size):
            trade['type'] = 'entry'
            self.entry_fill_price = trade['price']
            print(f"[{self.name}] FILLED {trade['side']} {trade['size']} @ {trade['price']:.2f} (Entry)")
        else:
            trade['type'] = 'exit'
            pnl = self._calc_pnl(trade)
            trade['pnl'] = pnl 
            print(f"[{self.name}] CLOSED {trade['side']} {trade['size']} @ {trade['price']:.2f} | PnL: ${pnl:.2f}")

    def _calc_pnl(self, exit_trade):
        # Simple FIFO PnL approximation for this trade leg
        entry = self.entry_fill_price
        exit_px = exit_trade['price']
        qty = exit_trade['size']
        side_mult = 1 if exit_trade['side'] == 'SELL' else -1 # If we Sold to close, we were Long (1)
        
        gross = (exit_px - entry) * qty * side_mult
        net = gross - exit_trade['commission'] # Entry comm is sunk cost, but generally we track round trip
        # NOTE: Manager logs commission per leg.
        return net 

    def on_bar(self, bar):
        # Update History
        self.history.append(bar.close)
        
        if len(self.history) < self.length: return

        # Calculate Indicators
        prices = list(self.history)[-self.length:]
        sma = sum(prices) / self.length
        variance = sum((p - sma) ** 2 for p in prices) / self.length
        std = variance ** 0.5
        
        upper = sma + (self.mult * std)
        lower = sma - (self.mult * std)
        
        self.history_upper.append(upper)
        self.history_lower.append(lower)
        
        if len(self.history_upper) < 2: return
            
        current_close = bar.close
        prev_close = prices[-2]
        
        current_lower = lower
        prev_lower = self.history_lower[-2]
        
        current_upper = upper
        prev_upper = self.history_upper[-2]
        
        # Signals
        long_signal = (prev_close < prev_lower) and (current_close > current_lower)
        short_signal = (prev_close >= prev_upper) and (current_close < current_upper)
        
        allow_long = (S1_DIRECTION == 0) or (S1_DIRECTION == 1)
        
        # Entry Logic (Market on Open of Next Bar)
        if allow_long and long_signal and self.position_size == 0:
            # Setup dynamic sizing function
            def size_fn(price):
                eq = self.manager.portfolio.equity() 
                return (eq * self.pct_equity) / price
                
            self.manager.submit_market_on_open(self.name, 1, size_fn)
            
        # Exit Logic
        # If Long, and Short Signal -> Close
        if self.position_size > 0 and short_signal:
             def size_fn_close(price):
                 return abs(self.position_size)
                 
             self.manager.submit_market_on_open(self.name, -1, size_fn_close) # Sell to close
             
    def on_tick(self, tick):
        pass # BB uses Close prices only

class ThreeEMAStrategy:
    """Strategy 2: 3EMA + ATR"""
    def __init__(self, manager, name="3EMA"):
        self.manager = manager
        self.name = name
        
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
        
        self.position_size = 0.0
        self.entry_fill_price = 0.0
        
        # Real-world: TP/SL are relative to FILL price, not Signal price.
        self.tp_price = 0.0
        self.sl_price = 0.0
        
    def on_fill(self, trade):
        if trade['strategy'] != self.name: return
        
        prev_size = self.position_size
        size_signed = trade['size'] if trade['side'] == 'BUY' else -trade['size']
        self.position_size += size_signed
        
        if abs(self.position_size) > abs(prev_size):
            trade['type'] = 'entry'
            self.entry_fill_price = trade['price']
            
            # Set TP/SL based on FILL PRICE
            self.tp_price = self.entry_fill_price + (self.atr * S2_TP_ATR_MULT)
            self.sl_price = self.entry_fill_price - (self.atr * S2_SL_ATR_MULT)
            
            print(f"[{self.name}] FILLED {trade['side']} {trade['size']} @ {trade['price']:.2f} | TP: {self.tp_price:.2f} SL: {self.sl_price:.2f} (Entry)")
        else:
            trade['type'] = 'exit'
            pnl = self._calc_pnl(trade)
            trade['pnl'] = pnl
            print(f"[{self.name}] CLOSED {trade['side']} {trade['size']} @ {trade['price']:.2f} | PnL: ${pnl:.2f}")

    def _calc_pnl(self, exit_trade):
        entry = self.entry_fill_price
        exit_px = exit_trade['price']
        qty = exit_trade['size']
        side_mult = 1 if exit_trade['side'] == 'SELL' else -1 
        gross = (exit_px - entry) * qty * side_mult
        return gross - exit_trade['commission']

    def _calc_ema(self, price, prev_ema, length):
        if prev_ema == 0.0: return price
        alpha = 2 / (length + 1)
        return (price - prev_ema) * alpha + prev_ema

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

        # Logic
        curr_mid = self.ema_mid
        prev_mid = self.history_ema_mid[-2]
        curr_slow = self.ema_slow
        prev_slow = self.history_ema_slow[-2]
        curr_fast = self.ema_fast
        prev_fast = self.history_ema_fast[-2]
        
        entry_signal = (prev_mid <= prev_slow) and (curr_mid > curr_slow)
        exit_signal = (prev_fast >= prev_mid) and (curr_fast < curr_mid)
        
        # Execution
        if self.position_size > 0:
            if exit_signal:
                def size_fn_close(price): return abs(self.position_size)
                self.manager.submit_market_on_open(self.name, -1, size_fn_close)
                
        elif self.position_size == 0:
            if entry_signal:
                def size_fn(price):
                    eq = self.manager.portfolio.equity()
                    return (eq * S2_PCT_EQUITY) / price
                self.manager.submit_market_on_open(self.name, 1, size_fn)

    def on_tick(self, tick):
        # Intra-bar Check: TP / SL
        if self.position_size > 0:
            # Conservative Order: Check SL FIRST
            if tick.price <= self.sl_price:
                 # STOP LOSS HIT - Immediate Exit Request
                 def size_fn_close(price): return abs(self.position_size)
                 # Realistically, this would trigger a MARKET order NOW.
                 # Using submit_market_on_open triggers it NEXT tick.
                 # Given tick granularity, next tick is acceptable "slippage".
                 self.manager.submit_market_on_open(self.name, -1, size_fn_close)
                 
            elif tick.price >= self.tp_price:
                 # TAKE PROFIT HIT
                 def size_fn_close(price): return abs(self.position_size)
                 self.manager.submit_market_on_open(self.name, -1, size_fn_close)

class CombinedStrategy(Strategy):
    def __init__(self, engine, portfolio):
        self.engine = engine
        self.portfolio = portfolio
        self.aggregator = BarAggregator(BAR_INTERVAL_MIN)
        
        # 1. Load Config & Specs
        self.loader = DataLoader(CONFIG_FILE)
        # Assuming we are running on BTC for this backtest
        self.spec = self.loader.get_symbol_spec("BTC")
        
        # 2. Init Manager
        self.manager = OrderManager(engine, portfolio, self.spec)
        
        self.trades_list = []
        self.equity_curve = []
        self.last_equity_day = -1
        
        # 3. Init Strategies with Manager
        self.bb = BollingerBandsStrategy(self.manager, name="BB")
        self.ema = ThreeEMAStrategy(self.manager, name="3EMA")
        
    def on_tick(self, tick):
        
        # A. Process Pending Orders (Execution Phase)
        # This executes orders generated in the PREVIOUS tick/bar
        filled_orders = self.manager.process_pending_orders(tick)
        
        # B. Distribute Fills to Strategies
        for order in filled_orders:
            fill_info = order['fill_info']
            self.bb.on_fill(fill_info)
            self.ema.on_fill(fill_info)
            self.trades_list.append(fill_info) # Log globally
            
        # C. Strategy Logic (Signal Phase)
        # 1. Intra-bar checks
        self.ema.on_tick(tick)
        self.bb.on_tick(tick)
        
        # 2. Bar Aggregation
        bar = self.aggregator.on_tick(tick)
        if bar:
            self.bb.on_bar(bar)
            self.ema.on_bar(bar)
            
        # D. Equity Curve Tracking
        self.check_daily_equity(tick.timestamp)

    def check_daily_equity(self, timestamp):
        # Timestamp is ns.
        ts_sec = timestamp / 1e9
        day_idx = int(ts_sec // 86400)
        
        if day_idx > self.last_equity_day:
            if self.last_equity_day != -1:
                # Capture end of day equity
                # Note: This is RAW equity. 
                # Real Net Liq should deduct open commissions? 
                # Our Strategy calculates realized PnL.
                # Portfolio.equity() from C++ is Mark-to-Market.
                self.equity_curve.append(self.portfolio.equity())
            else:
                 self.equity_curve.append(self.portfolio.equity())
            self.last_equity_day = day_idx

    def on_start(self):
        print("Starting Real-World Backtest V2...")
        print(f"Asset Spec: {self.spec}")
        
    def on_end(self):
        print("Backtest Complete. Closing any open positions for reporting...")
        # Since we want a robust report, we can force close via manager?
        # Or just leave open and report Net Liq (Mark to Market).
        pass

    def on_bar(self, bar):
        pass

    def on_fill(self, fill):
        # This is the C++ engine callback. 
        # We don't need to do anything here because we handle fills 
        # via our OrderManager.process_pending_orders() loop.
        pass

def calculate_and_print_returns(equity_curve, initial_capital, start_date_str='2021-01-01', final_net_liq=None):
    """ It Calculates Year-on-Year and Quarterly returns from daily equity curve."""
    if not equity_curve:
        print("No equity curve data to analyze.")
        return

    try:
        # Create DataFrame
        dates = [pd.Timestamp(start_date_str) + timedelta(days=i) for i in range(len(equity_curve))]
        
        if final_net_liq is not None:
             # Ensure last point matches final liquidating value
             if len(equity_curve) > 0:
                 equity_curve[-1] = final_net_liq
             
        df = pd.DataFrame({'equity': equity_curve}, index=dates)
        
        # Resample to Yearly and Quarterly
        yearly = df['equity'].resample('Y').last()
        quarterly = df['equity'].resample('Q').last()
        
        print("\n" + "="*40)
        print(" PERIODIC RETURNS ANALYSIS")
        print("="*40)
        
        # --- YEARLY ---
        print("\n[ YEAR-ON-YEAR RETURNS ]")
        print(f"{'Year':<10} | {'Start Equity':<15} | {'End Equity':<15} | {'Return':<10}")
        print("-" * 58)
        
        y_start = initial_capital
        for date, y_end in yearly.items():
            if y_start == 0: y_start = 1 # Avoid div by zero
            ret = ((y_end - y_start) / y_start) * 100
            print(f"{date.year:<10} | ${y_start:<14,.2f} | ${y_end:<14,.2f} | {ret:>6.2f}%")
            y_start = y_end 

        # --- QUARTERLY ---
        print("\n[ QUARTERLY RETURNS ]")
        print(f"{'Period':<15} | {'Start Equity':<15} | {'End Equity':<15} | {'Return':<10}")
        print("-" * 63)
        
        q_start = initial_capital
        for date, q_end in quarterly.items():
            if q_start == 0: q_start = 1
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
                if y_start == 0: y_start = 1
                ret = ((y_end - y_start) / y_start) * 100
                f.write(f"Year {date.year}: {ret:.2f}% (${y_start:.2f} -> ${y_end:.2f})\n")
                y_start = y_end
            
            f.write("\n[ QUARTERLY RETURNS ]\n")
            q_start = initial_capital
            for date, q_end in quarterly.items():
                if q_start == 0: q_start = 1
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
    
    initial_capital = 100000.0
    slippage = fe.SlippageConfig()
    slippage.fixed_bps = 0.0 # We handle slippage in Python Manager now!
    
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
    
    start_time = datetime.now()
    event_loop.run(stream, strategy, engine, portfolio)
    end_time = datetime.now()
    
    # Results
    duration = (end_time - start_time).total_seconds()
    
    # Final Equity from Portfolio (includes positions mark-to-market)
    final_equity = portfolio.equity()
    
    # Total Trades from our Manager Log
    total_trades = len(strategy.trades_list)
    total_comm = sum(t['commission'] for t in strategy.trades_list)
    
    print("\n" + "=" * 40)
    print(" V2 REAL-WORLD RESULTS ")
    print("=" * 40)
    print(f"Initial Capital:       ${initial_capital:,.2f}")
    print(f"Final Equity:          ${final_equity:,.2f}")
    print(f"Total Return:          {((final_equity - initial_capital)/initial_capital)*100:.2f}%")
    print("-" * 40)
    print(f"Total Trades:          {total_trades}")
    print(f"Total Commission:      ${total_comm:,.2f}")
    print(f"Execution Time:        {duration:.2f} seconds")
    print("=" * 40)
    
    # Export
    print("Exporting for Dashboard...")
    dashboard_path = os.path.join(project_root, "dashboard_data")
    exporter = DashboardExporter(dashboard_path)
    exporter.export(strategy.equity_curve, strategy.trades_list, initial_capital)
    calculate_and_print_returns(strategy.equity_curve, initial_capital, final_net_liq=final_equity)

if __name__ == "__main__":
    main()
