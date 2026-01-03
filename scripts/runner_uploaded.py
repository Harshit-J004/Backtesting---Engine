from __future__ import annotations

import json
import sys
import importlib.util
from pathlib import Path


def load_strategy_module(strategy_path: Path):
    """
    Correct import-by-path:
    - creates a unique module name
    - registers it in sys.modules BEFORE exec_module (fixes dataclass __dict__ crash)
    """
    strategy_path = strategy_path.resolve()
    module_name = f"uploaded_strategy_{strategy_path.stem}"

    spec = importlib.util.spec_from_file_location(module_name, str(strategy_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to create import spec for: {strategy_path}")

    mod = importlib.util.module_from_spec(spec)

    # IMPORTANT: dataclasses needs sys.modules entry for cls.__module__
    sys.modules[module_name] = mod

    spec.loader.exec_module(mod)
    return mod


def main():
    # ------------------------------------------------------------------
    # You are in WSL (because traceback shows /mnt/c/...), so use /mnt/c
    # ------------------------------------------------------------------
    base = Path("/mnt/c/Users/spkri/OneDrive/Desktop/Felix Corporation")

    # Strategy + CSV (your exact location)
    strategy_path = base / "rsi_eurusd_prototype.py"
    csv_path = base / "EURUSD_M1.csv"

    # Repo project root (your linux repo)
    project_root = Path("/home/krish/Felix_Engine_Copy_V/Backtesting---Engine")
    out_dir = project_root / "dashboard_data"

    # Ensure imports inside strategy work (scripts.*, felix.*, etc.)
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "python"))
    sys.path.insert(0, str(strategy_path.parent))  # allow local imports near strategy

    # Validate files exist
    if not strategy_path.exists():
        raise FileNotFoundError(f"Strategy not found: {strategy_path}")
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    # Load strategy
    mod = load_strategy_module(strategy_path)

    # Validate contract
    if not hasattr(mod, "run_pipeline"):
        raise RuntimeError("Strategy missing required function: run_pipeline(...)")

    # Build AssetSpec (use your project AssetSpec if available)
    try:
        from scripts.prototype import AssetSpec  # type: ignore
        asset = AssetSpec(
            name="EURUSD",
            symbol_id=1,
            tick_size=0.00001,
            lot_size=1.0,
            commission_bps=0.02,
            slippage_bps=0.02,
            spread=0.0,
        )
    except Exception:
        class _Asset:
            name = "EURUSD"
            symbol_id = 1
            tick_size = 0.00001
            lot_size = 1.0
            commission_bps = 0.02
            slippage_bps = 0.02
            spread = 0.0
        asset = _Asset()

    # -------------------------
    # Your UI params
    # -------------------------
    initial_capital = 100000

    # commission bps = 0.02%  -> 0.0002
    commission_bps = 0.02
    commission_rate = float(commission_bps) / 100.0

    run_config = {
        "asset": "EURUSD",
        "symbol_id": 1,
        "spread": 0.0,

        "initial_capital": float(initial_capital),
        "commission_rate": float(commission_rate),

        "params": {
            "rsi_len": 22,

            # keeping these available for later rules
            "stop_loss_pct": 4.0,
            "target_profit_pct": 6.0,
            "max_trades_per_day": 100,
            "threshold_balance": 50000.0,

            # OPTIONAL: ensure dates match your CSV year range
            # "start_date": "2021-01-01",
            # "end_date": "2021-12-31",
        },
    }

    def log(msg: str):
        print(msg)

    print("====================================")
    print(" RUN STRATEGY (CLI VERIFY) ")
    print("====================================")
    print("Strategy:", strategy_path)
    print("CSV:", csv_path)
    print("Output dir:", out_dir)
    print("Run config:", json.dumps(run_config, indent=2))
    print("------------------------------------")

    outputs = mod.run_pipeline(
        csv_paths=[str(csv_path)],
        run_config=run_config,
        asset=asset,
        out_dir=str(out_dir),
        log=log,
    )

    print("\n✅ DONE")
    print(json.dumps(outputs, indent=2))

    # Show first lines
    for name in ["basket_summary.csv", "trade_log.csv", "equity_curve.csv"]:
        p = out_dir / name
        print(f"\n--- {p} ---")
        if p.exists():
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for _ in range(5):
                    line = f.readline()
                    if not line:
                        break
                    print(line.rstrip())
        else:
            print("MISSING")


if __name__ == "__main__":
    main()
