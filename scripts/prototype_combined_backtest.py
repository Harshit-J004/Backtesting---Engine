"""
Prototype Combined Strategy (engine matching, MT5-like format)

Built on scripts/prototype.py template.
Matches combined_backtest_long_only_v2.py - uses Python-side OrderManager.

Exports:
- STRATEGY_META
- StrategyImpl(Strategy)

Logic:
- BB on 45m derived bars (mean reversion) - CROSSOVER signals
- 3EMA + ATR on 45m bars (trend following) - CROSSOVER signals
- ATR-based TP/SL checked on every tick
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "python"))

try:
    import felix_engine as fe
except ImportError:
    fe = None

from scripts.prototype import (
    AssetSpec,
    safe_get,
)
from felix.strategy.base import Strategy  # type: ignore


STRATEGY_META: Dict[str, Any] = {
    "name": "PrototypeCombined",
    "version": "2.1",
    "description": "Combined strategy (BB + 3EMA crossovers on 45m bars). Uses OrderManager like combined_backtest_long_only_v2.py.",
    "params": {
        # BB Strategy params (matching S1_* in combined_backtest_long_only_v2.py)
        "bb_length": {"type": "int", "default": 20, "min": 5},
        "bb_mult": {"type": "float", "default": 2.5, "min": 0.1},
        "bb_pct_equity": {"type": "float", "default": 0.5, "min": 0.0, "max": 1.0},
        
        # EMA Strategy params (matching S2_* in combined_backtest_long_only_v2.py)
        "ema_slow": {"type": "int", "default": 30, "min": 1},
        "ema_mid": {"type": "int", "default": 12, "min": 1},
        "ema_fast": {"type": "int", "default": 7, "min": 1},
        "atr_len": {"type": "int", "default": 7, "min": 1},
        "tp_atr_mult": {"type": "float", "default": 4.0, "min": 0.1},
        "sl_atr_mult": {"type": "float", "default": 1.0, "min": 0.1},
        "ema_pct_equity": {"type": "float", "default": 0.1, "min": 0.0, "max": 1.0},
        
        # Bar interval
        "bar_interval_min": {"type": "int", "default": 45, "min": 1},
        
        # Strategy toggles
        "enable_bb": {"type": "bool", "default": True},
        "enable_ema": {"type": "bool", "default": True},
        "long_only": {"type": "bool", "default": True},
    },
}


# ----------------------------- Order Manager (from combined_backtest_long_only_v2.py) -----------------------------

class OrderStatus:
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELED = "CANCELED"


class OrderManager:
    """Simulates a Real Exchange/Terminal (MT5 Style) - from combined_backtest_long_only_v2.py"""
    
    def __init__(self, engine: Any, portfolio: Any, spec: Dict[str, Any]):
        self.engine = engine
        self.portfolio = portfolio
        self.spec = spec
        
        self.orders: List[Dict] = []
        self.working_orders: List[Dict] = []
        self.trade_log: List[Dict] = []
        self.open_positions: Dict[str, float] = {}
        
        self.order_id_counter = 0
        
    def submit_market_on_open(self, strategy_id: str, side: int, size_setup: Any) -> int:
        """Market Order: Fills at Next Tick"""
        return self._submit_order(strategy_id, 'MARKET_ON_OPEN', side, size_setup, price=0)

    def _submit_order(self, strategy_id: str, order_type: str, side: int, size_setup: Any, price: float) -> int:
        order = {
            'id': self._next_id(),
            'strategy_id': strategy_id,
            'type': order_type,
            'side': side, 
            'size_setup': size_setup,
            'price': price,
            'status': OrderStatus.OPEN,
            'created_at': -1
        }
        self.orders.append(order)
        self.working_orders.append(order)
        return order['id']
        
    def process_pending_orders(self, tick: Any) -> List[Dict]:
        """Called on EVERY tick. Matches and fills pending orders."""
        executed_orders = []
        price = tick.price
        
        for order in self.working_orders[:]:
            if order['status'] != OrderStatus.OPEN:
                continue
            
            fill_price = None
            
            if order['type'] == 'MARKET_ON_OPEN':
                fill_price = price
            
            if fill_price is not None:
                # Apply slippage
                slippage_bps = self.spec.get('slippage_bps', 0)
                if order['side'] == 1:
                    fill_price *= (1 + slippage_bps / 10000)
                else:
                    fill_price *= (1 - slippage_bps / 10000)
                
                # Apply tick size
                tick_size = self.spec.get('tick_size', 0.01)
                fill_price = round(fill_price / tick_size) * tick_size
                
                # Calculate size
                lot_size = self.spec.get('lot_size', 0.001)
                
                if order.get('total_size') is None:
                    if callable(order['size_setup']):
                        raw_size = order['size_setup'](fill_price)
                    else:
                        raw_size = order['size_setup']
                    order['total_size'] = (raw_size // lot_size) * lot_size
                
                exec_size = order['total_size']
                if exec_size <= 0:
                    order['status'] = OrderStatus.CANCELED
                    self.working_orders.remove(order)
                    continue
                
                # Commission
                comm_bps = self.spec.get('commission_bps', 0)
                comm_cost = (exec_size * fill_price) * (comm_bps / 10000)
                
                # Log trade
                trade = {
                    'id': order['id'],
                    'strategy': order['strategy_id'],
                    'timestamp': tick.timestamp,
                    'side': 'BUY' if order['side'] == 1 else 'SELL',
                    'price': fill_price,
                    'size': exec_size,
                    'commission': comm_cost,
                }
                self.trade_log.append(trade)
                
                # Update position
                curr_pos = self.open_positions.get(order['strategy_id'], 0)
                self.open_positions[order['strategy_id']] = curr_pos + (exec_size * order['side'])
                
                # Mark filled
                order['status'] = OrderStatus.FILLED
                order['fill_info'] = trade
                executed_orders.append(order)
                self.working_orders.remove(order)
                
                # Sync to C++ engine for portfolio tracking
                if fe is not None:
                    fe_order = fe.Order()
                    fe_order.symbol_id = self.spec['symbol_id']
                    fe_order.side = fe.Side.BUY if order['side'] == 1 else fe.Side.SELL
                    fe_order.order_type = fe.OrderType.MARKET
                    fe_order.size = exec_size
                    fe_order.price = fill_price
                    fe_order.timestamp = tick.timestamp
                    self.engine.submit_order(fe_order)
        
        return executed_orders

    def _next_id(self) -> int:
        self.order_id_counter += 1
        return self.order_id_counter


# ----------------------------- Bar Aggregator -----------------------------

@dataclass
class Bar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class BarAggregator:
    """Aggregates ticks into N-min bars (matching combined_backtest_long_only_v2.py)"""
    def __init__(self, interval_minutes: int):
        self.interval_minutes = int(interval_minutes)
        self.current_bar: Optional[Bar] = None
        self.last_period_index: int = -1
        
    def on_tick(self, tick: Any) -> Optional[Bar]:
        ts_seconds = tick.timestamp / 1e9
        minutes_total = int(ts_seconds // 60)
        period_index = minutes_total // self.interval_minutes
        
        completed_bar = None
        
        if period_index > self.last_period_index:
            if self.last_period_index != -1 and self.current_bar:
                completed_bar = self.current_bar
            
            self.current_bar = Bar(
                timestamp=tick.timestamp,
                open=tick.price,
                high=tick.price,
                low=tick.price,
                close=tick.price,
                volume=0
            )
            self.last_period_index = period_index
        else:
            if self.current_bar:
                self.current_bar.high = max(self.current_bar.high, tick.price)
                self.current_bar.low = min(self.current_bar.low, tick.price)
                self.current_bar.close = tick.price
        
        return completed_bar


# ----------------------------- BB Sub-Strategy (matching BollingerBandsStrategy) -----------------------------

class BBStrategy:
    """Bollinger Bands Strategy (from combined_backtest_long_only_v2.py)"""
    
    def __init__(self, manager: OrderManager, name: str = "BB", 
                 length: int = 20, mult: float = 2.5, pct_equity: float = 0.5):
        self.manager = manager
        self.name = name
        self.length = length
        self.mult = mult
        self.pct_equity = pct_equity
        
        self.history: deque[float] = deque(maxlen=length + 1)
        self.history_lower: deque[float] = deque(maxlen=2)
        self.history_upper: deque[float] = deque(maxlen=2)
        
        self.entry_fill_price: float = 0.0
        self.position_size: float = 0.0
        
    def on_fill(self, trade: Dict) -> None:
        if trade['strategy'] != self.name:
            return
        
        prev_size = self.position_size
        size_signed = trade['size'] if trade['side'] == 'BUY' else -trade['size']
        self.position_size += size_signed
        
        if abs(self.position_size) > abs(prev_size):
            trade['type'] = 'entry'
            self.entry_fill_price = trade['price']
            print(f"[{self.name}] FILLED {trade['side']} {trade['size']:.6f} @ {trade['price']:.2f} (Entry)")
        else:
            trade['type'] = 'exit'
            pnl = self._calc_pnl(trade)
            trade['pnl'] = pnl
            print(f"[{self.name}] CLOSED {trade['side']} {trade['size']:.6f} @ {trade['price']:.2f} | PnL: ${pnl:.2f}")

    def _calc_pnl(self, exit_trade: Dict) -> float:
        entry = self.entry_fill_price
        exit_px = exit_trade['price']
        qty = exit_trade['size']
        side_mult = 1 if exit_trade['side'] == 'SELL' else -1
        gross = (exit_px - entry) * qty * side_mult
        return gross - exit_trade['commission']

    def on_bar(self, bar: Bar) -> None:
        self.history.append(bar.close)
        
        if len(self.history) < self.length:
            return
        
        prices = list(self.history)[-self.length:]
        sma = sum(prices) / self.length
        variance = sum((p - sma) ** 2 for p in prices) / self.length
        std = variance ** 0.5
        
        upper = sma + (self.mult * std)
        lower = sma - (self.mult * std)
        
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
        
        # Crossover signals
        long_signal = (prev_close < prev_lower) and (current_close > current_lower)
        short_signal = (prev_close >= prev_upper) and (current_close < current_upper)
        
        # Entry
        if long_signal and self.position_size == 0:
            def size_fn(price: float) -> float:
                eq = self.manager.portfolio.equity()
                return (eq * self.pct_equity) / price
            self.manager.submit_market_on_open(self.name, 1, size_fn)
        
        # Exit
        if self.position_size > 0 and short_signal:
            def size_fn_close(price: float) -> float:
                return abs(self.position_size)
            self.manager.submit_market_on_open(self.name, -1, size_fn_close)


# ----------------------------- EMA Sub-Strategy (matching ThreeEMAStrategy) -----------------------------

class EMAStrategy:
    """3EMA + ATR Strategy (from combined_backtest_long_only_v2.py)"""
    
    def __init__(self, manager: OrderManager, name: str = "3EMA",
                 slow_len: int = 30, mid_len: int = 12, fast_len: int = 7,
                 atr_len: int = 7, tp_mult: float = 4.0, sl_mult: float = 1.0,
                 pct_equity: float = 0.1):
        self.manager = manager
        self.name = name
        
        self.slow_len = slow_len
        self.mid_len = mid_len
        self.fast_len = fast_len
        self.atr_len = atr_len
        self.tp_mult = tp_mult
        self.sl_mult = sl_mult
        self.pct_equity = pct_equity
        
        self.ema_fast: float = 0.0
        self.ema_mid: float = 0.0
        self.ema_slow: float = 0.0
        
        self.history_ema_fast: deque[float] = deque(maxlen=2)
        self.history_ema_mid: deque[float] = deque(maxlen=2)
        self.history_ema_slow: deque[float] = deque(maxlen=2)
        
        self.prev_close: float = 0.0
        self.atr: float = 0.0
        
        self.position_size: float = 0.0
        self.entry_fill_price: float = 0.0
        self.tp_price: float = 0.0
        self.sl_price: float = 0.0

    def on_fill(self, trade: Dict) -> None:
        if trade['strategy'] != self.name:
            return
        
        prev_size = self.position_size
        size_signed = trade['size'] if trade['side'] == 'BUY' else -trade['size']
        self.position_size += size_signed
        
        if abs(self.position_size) > abs(prev_size):
            trade['type'] = 'entry'
            self.entry_fill_price = trade['price']
            self.tp_price = self.entry_fill_price + (self.atr * self.tp_mult)
            self.sl_price = self.entry_fill_price - (self.atr * self.sl_mult)
            print(f"[{self.name}] FILLED {trade['side']} {trade['size']:.6f} @ {trade['price']:.2f} | TP: {self.tp_price:.2f} SL: {self.sl_price:.2f} (Entry)")
        else:
            trade['type'] = 'exit'
            pnl = self._calc_pnl(trade)
            trade['pnl'] = pnl
            self.tp_price = 0.0
            self.sl_price = 0.0
            print(f"[{self.name}] CLOSED {trade['side']} {trade['size']:.6f} @ {trade['price']:.2f} | PnL: ${pnl:.2f}")

    def _calc_pnl(self, exit_trade: Dict) -> float:
        entry = self.entry_fill_price
        exit_px = exit_trade['price']
        qty = exit_trade['size']
        side_mult = 1 if exit_trade['side'] == 'SELL' else -1
        gross = (exit_px - entry) * qty * side_mult
        return gross - exit_trade['commission']

    def _calc_ema(self, price: float, prev_ema: float, length: int) -> float:
        if prev_ema == 0.0:
            return price
        alpha = 2.0 / (length + 1.0)
        return (price - prev_ema) * alpha + prev_ema

    def on_bar(self, bar: Bar) -> None:
        self.ema_fast = self._calc_ema(bar.close, self.ema_fast, self.fast_len)
        self.ema_mid = self._calc_ema(bar.close, self.ema_mid, self.mid_len)
        self.ema_slow = self._calc_ema(bar.close, self.ema_slow, self.slow_len)
        
        self.history_ema_fast.append(self.ema_fast)
        self.history_ema_mid.append(self.ema_mid)
        self.history_ema_slow.append(self.ema_slow)
        
        # ATR
        if self.prev_close > 0:
            tr = max(bar.high - bar.low,
                     abs(bar.high - self.prev_close),
                     abs(bar.low - self.prev_close))
        else:
            tr = bar.high - bar.low
        
        self.prev_close = bar.close
        
        if self.atr == 0:
            self.atr = tr
        else:
            alpha = 1.0 / self.atr_len
            self.atr = (tr * alpha) + (self.atr * (1 - alpha))
        
        if len(self.history_ema_slow) < 2:
            return
        
        curr_mid = self.ema_mid
        prev_mid = self.history_ema_mid[-2]
        curr_slow = self.ema_slow
        prev_slow = self.history_ema_slow[-2]
        curr_fast = self.ema_fast
        prev_fast = self.history_ema_fast[-2]
        
        entry_signal = (prev_mid <= prev_slow) and (curr_mid > curr_slow)
        exit_signal = (prev_fast >= prev_mid) and (curr_fast < curr_mid)
        
        # Exit first
        if self.position_size > 0 and exit_signal:
            def size_fn_close(price: float) -> float:
                return abs(self.position_size)
            self.manager.submit_market_on_open(self.name, -1, size_fn_close)
        # Entry
        elif self.position_size == 0 and entry_signal:
            def size_fn(price: float) -> float:
                eq = self.manager.portfolio.equity()
                return (eq * self.pct_equity) / price
            self.manager.submit_market_on_open(self.name, 1, size_fn)

    def on_tick(self, tick: Any) -> None:
        """Intra-bar TP/SL check"""
        if self.position_size > 0:
            if tick.price <= self.sl_price and self.sl_price > 0:
                def size_fn_close(price: float) -> float:
                    return abs(self.position_size)
                self.manager.submit_market_on_open(self.name, -1, size_fn_close)
            elif tick.price >= self.tp_price and self.tp_price > 0:
                def size_fn_close(price: float) -> float:
                    return abs(self.position_size)
                self.manager.submit_market_on_open(self.name, -1, size_fn_close)


# ----------------------------- Main Strategy -----------------------------

class StrategyImpl(Strategy):
    """
    Combined strategy matching combined_backtest_long_only_v2.py.
    Uses OrderManager for proper order execution and fill handling.
    """
    
    def __init__(
        self,
        engine: Any,
        portfolio: Any,
        risk_engine: Any,
        run_config: Dict[str, Any],
        asset_spec: AssetSpec,
    ):
        super().__init__()
        self.engine = engine
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        self.run_config = run_config
        self.asset = asset_spec

        self._initial_capital = float(run_config.get("initial_capital", 10_000.0))

        # Load params
        p = run_config.get("params") or {}
        meta = STRATEGY_META["params"]

        def _get(k: str):
            return p.get(k, meta[k]["default"])

        # Build spec dict for OrderManager
        self.spec = {
            'symbol_id': asset_spec.symbol_id,
            'tick_size': asset_spec.tick_size,
            'lot_size': asset_spec.lot_size,
            'commission_bps': asset_spec.commission_bps,
            'slippage_bps': asset_spec.slippage_bps,
        }
        
        # Bar interval
        bar_interval_min = int(_get("bar_interval_min"))
        
        # Strategy toggles
        self.enable_bb = bool(_get("enable_bb"))
        self.enable_ema = bool(_get("enable_ema"))

        # Initialize OrderManager
        self.manager = OrderManager(engine, portfolio, self.spec)
        
        # Initialize bar aggregator
        self.aggregator = BarAggregator(bar_interval_min)
        
        # Initialize sub-strategies
        self.bb = BBStrategy(
            self.manager, name="BB",
            length=int(_get("bb_length")),
            mult=float(_get("bb_mult")),
            pct_equity=float(_get("bb_pct_equity"))
        ) if self.enable_bb else None
        
        self.ema = EMAStrategy(
            self.manager, name="3EMA",
            slow_len=int(_get("ema_slow")),
            mid_len=int(_get("ema_mid")),
            fast_len=int(_get("ema_fast")),
            atr_len=int(_get("atr_len")),
            tp_mult=float(_get("tp_atr_mult")),
            sl_mult=float(_get("sl_atr_mult")),
            pct_equity=float(_get("ema_pct_equity"))
        ) if self.enable_ema else None

        # Outputs for dashboard
        self.trades_list: List[Dict] = []
        self.equity_curve: List[float] = []
        self.trades: List[Dict] = []  # Alias for compatibility
        self._last_equity_day = -1

        # Debug counters
        self._tick_count = 0
        self._bar_count = 0

        print(f"[STRATEGY] Initialized PrototypeCombined v2.1 (OrderManager)")
        print(f"[STRATEGY] Asset: {asset_spec.name} (symbol_id={asset_spec.symbol_id})")
        print(f"[STRATEGY] Spec: lot_size={self.spec['lot_size']}, tick_size={self.spec['tick_size']}")
        print(f"[STRATEGY] Initial Capital: ${self._initial_capital:,.2f}")
        print(f"[STRATEGY] Bar Interval: {bar_interval_min} minutes")
        print(f"[STRATEGY] BB enabled: {self.enable_bb}, EMA enabled: {self.enable_ema}")

    def on_start(self) -> None:
        print(f"[STRATEGY] Starting backtest...")
        self._tick_count = 0
        self._bar_count = 0
        self.equity_curve.clear()
        self.trades_list.clear()
        self._last_equity_day = -1

    def on_end(self) -> None:
        total_trades = len(self.manager.trade_log)
        total_comm = sum(t.get('commission', 0) for t in self.manager.trade_log)
        
        print(f"\n[STRATEGY] Backtest complete")
        print(f"[STRATEGY] Total ticks: {self._tick_count}")
        print(f"[STRATEGY] Total bars: {self._bar_count}")
        print(f"[STRATEGY] Total trades: {total_trades}")
        print(f"[STRATEGY] Total commission: ${total_comm:.2f}")
        if self.bb:
            print(f"[STRATEGY] BB position: {self.bb.position_size}")
        if self.ema:
            print(f"[STRATEGY] EMA position: {self.ema.position_size}")
        print(f"[STRATEGY] Final equity: ${self.portfolio.equity():,.2f}")
        
        # Copy trades to output lists
        self.trades = self.manager.trade_log
        self.trades_list = self.manager.trade_log

    def on_bar(self, bar: Any) -> None:
        pass

    def on_tick(self, tick: Any) -> None:
        self._tick_count += 1
        
        if self._tick_count <= 3:
            print(f"[TICK #{self._tick_count}] ts={tick.timestamp} price={tick.price:.2f}")
        
        # A. Process pending orders (fills happen here!)
        filled_orders = self.manager.process_pending_orders(tick)
        
        # B. Distribute fills to sub-strategies
        for order in filled_orders:
            fill_info = order['fill_info']
            if self.bb:
                self.bb.on_fill(fill_info)
            if self.ema:
                self.ema.on_fill(fill_info)
            self.trades_list.append(fill_info)
        
        # C. Intra-bar TP/SL for EMA
        if self.ema:
            self.ema.on_tick(tick)
        
        # D. Bar aggregation and strategy signals
        bar = self.aggregator.on_tick(tick)
        if bar:
            self._bar_count += 1
            if self._bar_count <= 5:
                print(f"[BAR #{self._bar_count}] O={bar.open:.2f} H={bar.high:.2f} L={bar.low:.2f} C={bar.close:.2f}")
            
            if self.bb:
                self.bb.on_bar(bar)
            if self.ema:
                self.ema.on_bar(bar)
        
        # E. Daily equity sampling
        ts_sec = tick.timestamp / 1e9
        day_idx = int(ts_sec // 86400)
        if day_idx > self._last_equity_day:
            self.equity_curve.append(self.portfolio.equity())
            self._last_equity_day = day_idx

    def on_fill(self, fill: Any) -> None:
        # Not used - we handle fills via OrderManager
        pass
