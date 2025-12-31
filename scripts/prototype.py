"""
FELIX Strategy Prototype (MT5-like template)

This file defines the *required format* for Python strategies.

Strategy files must:
1) Define STRATEGY_META dict (name/version/params schema)
2) Define class StrategyImpl(Strategy) with callbacks:
   - on_start(self)
   - on_tick(self, tick)
   - on_bar(self, bar)
   - on_fill(self, fill)
   - on_end(self)

Constructor signature:
   __init__(self, engine, portfolio, risk_engine, run_config, asset_spec)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
import json
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "python"))

from felix.strategy.base import Strategy  # type: ignore


# ----------------------------- Strategy Template -----------------------------

STRATEGY_META: Dict[str, Any] = {
    "name": "PrototypeStrategy",
    "version": "1.0",
    "description": "Copy this file and fill in your logic.",
    "params": {
        # Example params:
        # "lookback": {"type": "int", "default": 20, "min": 1, "max": 500},
        # "risk_pct": {"type": "float", "default": 0.01, "min": 0.0, "max": 1.0},
    },
}


class StrategyImpl(Strategy):
    """
    Base strategy template. Copy into new strategy files.

    Engine callbacks (matching felix.strategy.base.Strategy):
      - on_start(self)
      - on_tick(self, tick)
      - on_bar(self, bar)
      - on_fill(self, fill)
      - on_end(self)
    """

    def __init__(
        self,
        engine: Any,
        portfolio: Any,
        risk_engine: Any,
        run_config: Dict[str, Any],
        asset_spec: "AssetSpec",
    ):
        super().__init__()
        self.engine = engine
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        self.run_config = run_config
        self.asset = asset_spec

        self._initial_capital = float(run_config.get("initial_capital", 10_000.0))

        # Outputs for dashboard (flat list of floats for equity_curve)
        self.equity_curve: List[float] = []
        self.trades: List[Dict[str, Any]] = []

    # -------------------- Helpers (inherit in strategies) --------------------

    def _get_equity(self) -> float:
        """Get current equity from portfolio (or fallback to initial)."""
        eq = safe_get(self.portfolio, "equity", "net_liquidation_value", "net_liq", default=None)
        if eq is not None:
            return float(eq)
        return float(self._initial_capital)

    def _calc_order_qty(self, equity: float, price: float, pct: float, lot_size: float, max_qty: float) -> float:
        """Calculate order quantity based on equity percentage."""
        if price <= 0:
            return 0.0
        notional = max(0.0, equity * pct)
        qty = notional / price
        qty = min(qty, max_qty)
        qty = round_to_step(qty, lot_size)
        return max(0.0, float(qty))

    # -------------------- Callbacks (override in strategies) --------------------

    def on_start(self) -> None:
        pass

    def on_tick(self, tick: Any) -> None:
        pass

    def on_bar(self, bar: Any) -> None:
        pass

    def on_fill(self, fill: Any) -> None:
        pass

    def on_end(self) -> None:
        pass


# ------------------------------ Shared Helpers ------------------------------

@dataclass(frozen=True)
class AssetSpec:
    name: str
    symbol_id: int
    tick_size: float
    lot_size: float
    commission_bps: float
    slippage_bps: float
    spread: float


def load_backtest_config(project_root_path: Path) -> Dict[str, Any]:
    cfg_path = project_root_path / "scripts" / "backtest_config.json"
    with open(cfg_path, "r") as f:
        return json.load(f)


def load_asset_spec(project_root_path: Path, asset_key: str = "BTC") -> AssetSpec:
    cfg = load_backtest_config(project_root_path)
    assets = cfg.get("assets", {})
    if asset_key not in assets:
        raise KeyError(f"Asset '{asset_key}' not found in backtest_config.json assets={list(assets.keys())}")

    a = assets[asset_key]
    return AssetSpec(
        name=asset_key,
        symbol_id=int(a["symbol_id"]),
        tick_size=float(a.get("tick_size", 0.01)),
        lot_size=float(a.get("lot_size", 1.0)),
        commission_bps=float(a.get("commission_bps", 0.0)),
        slippage_bps=float(a.get("slippage_bps", 0.0)),
        spread=float(a.get("spread", 0.0)),
    )


def round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return (value // step) * step


def safe_get(obj: Any, *names: str, default: Any = None) -> Any:
    """Return first existing attribute value from obj."""
    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            return v() if callable(v) else v
    return default


def submit_market_order(engine: Any, symbol_id: int, side: str, qty: float, debug: bool = True) -> bool:
    """
    Submit a market order to the engine.
    Returns True if order was submitted, False otherwise.
    """
    import felix_engine as fe

    side_u = side.upper()
    if qty <= 0:
        if debug:
            print(f"[ORDER] Skipped: qty={qty} <= 0")
        return False

    # Build Order object (matching combined_backtest_long_only_v2.py style)
    try:
        order = fe.Order()
        order.symbol_id = int(symbol_id)
        order.side = fe.Side.BUY if side_u == "BUY" else fe.Side.SELL
        order.order_type = fe.OrderType.MARKET
        order.size = float(qty)
        order.price = 0.0  # Market order

        if debug:
            print(f"[ORDER] Submitting {side_u} {qty:.6f} @ MARKET for symbol_id={symbol_id}")

        engine.submit_order(order)
        return True

    except Exception as e:
        if debug:
            print(f"[ORDER] ERROR submitting order: {e}")
        return False