"""
Prototype Terminal (MT5-like tester prompts via input()).

- Hardcoded strategy: scripts/prototype_combined_backtest.py
- Prompts tester inputs (deposit, data/bin, execution overrides)
- Strategy params are in the strategy file
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

import sys

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "python"))

from scripts.prototype import load_asset_spec, AssetSpec
from scripts.dashboard_exporter import DashboardExporter
from scripts import prototype_combined_backtest as strategy_module

try:
    import felix_engine as fe
except Exception as e:
    raise ImportError(
        "Could not import engine bindings as 'felix_engine'. "
        "Build/install the pybind module first."
    ) from e

from scripts.combined_backtest_long_only_v2 import calculate_and_print_returns

def _prompt(prompt: str, default: str = "") -> str:
    s = input(f"{prompt} [{default}]: ").strip()
    return s if s else default


def _prompt_float(prompt: str, default: float) -> float:
    s = _prompt(prompt, str(default))
    try:
        return float(s)
    except ValueError:
        return float(default)


def _prompt_int_blank(prompt: str, default: int | None = None) -> int | None:
    d = "" if default is None else str(default)
    s = _prompt(prompt, d).strip()
    if not s:
        return default
    try:
        return int(s)
    except ValueError:
        return default


def build_run_config() -> Tuple[Dict[str, Any], str, int | None]:
    print("\n" + "=" * 50)
    print(" FELIX PROTOTYPE TERMINAL")
    print("=" * 50)
    print(f"\nStrategy: {getattr(strategy_module, 'STRATEGY_META', {}).get('name', 'UNKNOWN')}")
    print(f"Version:  {getattr(strategy_module, 'STRATEGY_META', {}).get('version', '?')}\n")

    asset_key = _prompt("Asset key (from backtest_config.json)", "BTC")

    bin_name = _prompt("Data (.bin) filename in data/processed", "btcusdt_2023_2025.bin")
    bin_path = PROJECT_ROOT / "data" / "processed" / bin_name
    if not bin_path.exists():
        raise FileNotFoundError(f"Bin not found: {bin_path}")

    initial_capital = _prompt_float("Initial deposit", 10_000.0)

    # Symbol ID override (important: your bin may have symbol_id=2, config may have 1)
    symbol_id_override = _prompt_int_blank("Override symbol_id? (blank = config)", None)

    commission_bps_override = _prompt("Override commission_bps? (blank = config)", "")
    slippage_bps_override = _prompt("Override slippage_bps? (blank = config)", "")

    run_config: Dict[str, Any] = {
        "bin_path": str(bin_path),
        "initial_capital": float(initial_capital),
        "execution_overrides": {
            "commission_bps": float(commission_bps_override) if commission_bps_override else None,
            "slippage_bps": float(slippage_bps_override) if slippage_bps_override else None,
        },
        "params": {},  # Strategy uses its own defaults
    }
    return run_config, asset_key, symbol_id_override


def _make_risk_engine() -> Any:
    """Construct RiskEngine with default RiskLimits."""
    limits = fe.RiskLimits()
    return fe.RiskEngine(limits)


def run() -> None:
    run_config, asset_key, symbol_id_override = build_run_config()
    asset = load_asset_spec(PROJECT_ROOT, asset_key)

    # Apply symbol_id override if provided
    if symbol_id_override is not None:
        print(f"\n[CONFIG] Overriding symbol_id: {asset.symbol_id} -> {symbol_id_override}")
        asset = AssetSpec(
            name=asset.name,
            symbol_id=int(symbol_id_override),
            tick_size=asset.tick_size,
            lot_size=asset.lot_size,
            commission_bps=asset.commission_bps,
            slippage_bps=asset.slippage_bps,
            spread=asset.spread,
        )

    print(f"\n[CONFIG] Asset: {asset.name}")
    print(f"[CONFIG] Symbol ID: {asset.symbol_id}")
    print(f"[CONFIG] Initial Capital: ${run_config['initial_capital']:,.2f}")
    print(f"[CONFIG] Bin: {run_config['bin_path']}")

    # Load data
    print("\n[ENGINE] Loading data...")
    stream = fe.DataStream()
    stream.load(run_config["bin_path"])

    # Create engine components
    slippage_cfg = fe.SlippageConfig()
    slippage_cfg.fixed_bps = 0.0  # We handle slippage in strategy if needed

    matching = fe.MatchingEngine(slippage_cfg)
    portfolio = fe.Portfolio(run_config["initial_capital"])
    risk = _make_risk_engine()

    # Create strategy
    StrategyImpl = getattr(strategy_module, "StrategyImpl")
    strategy = StrategyImpl(matching, portfolio, risk, run_config, asset)

    # Run event loop
    print("\n[ENGINE] Starting backtest...")
    loop = fe.EventLoop()
    loop.set_matching_engine(matching)
    loop.set_portfolio(portfolio)

    loop.run(stream, strategy, matching, portfolio)

    # Results
    final_equity = portfolio.equity()
    initial_capital = run_config["initial_capital"]
    total_return = ((final_equity - initial_capital) / initial_capital) * 100

    print("\n" + "=" * 50)
    print(" BACKTEST RESULTS")
    print("=" * 50)
    print(f"Initial Capital:    ${initial_capital:,.2f}")
    print(f"Final Equity:       ${final_equity:,.2f}")
    print(f"Total Return:       {total_return:.2f}%")
    print(f"Total Trades:       {len(strategy.trades)}")
    print("=" * 50)

    # Export to dashboard
    print("\n[EXPORT] Exporting to dashboard_data...")
    dashboard_path = PROJECT_ROOT / "dashboard_data"
    exporter = DashboardExporter(str(dashboard_path))

    # equity_curve is now a flat list of floats
    equity_values = strategy.equity_curve

    # Downsample if too many points (every 1000th point)
    if len(equity_values) > 10000:
        step = len(equity_values) // 5000
        equity_values = equity_values[::step]
        print(f"[EXPORT] Downsampled equity curve to {len(equity_values)} points")

    # Pass initial_capital as required by DashboardExporter.export()
    exporter.export(equity_values, strategy.trades, initial_capital)

    print("\n✓ Backtest complete. Dashboard data exported.\n")

    # Calculate and print returns analysis
    if strategy.equity_curve:
        calculate_and_print_returns(
            strategy.equity_curve,
            initial_capital,
            start_date_str='2023-01-01',  # <-- adjust as needed
            final_net_liq=final_equity
        )


if __name__ == "__main__":
    run()