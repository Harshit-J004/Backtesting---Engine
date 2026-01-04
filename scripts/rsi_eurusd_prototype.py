
from __future__ import annotations

import os
import sys
import struct
from dataclasses import dataclass
from datetime import time as dtime
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

class Strategy:
    def __init__(self): pass
    def on_start(self): pass
    def on_tick(self, tick): pass
    def on_bar(self, bar): pass
    def on_fill(self, fill): pass
    def on_end(self): pass

# ============================
# Prototype-required metadata
# ============================
STRATEGY_META: Dict[str, Any] = {
    "name": "RSI_EURUSD_Trailing",
    "version": "1.0",
    "description": "RSI threshold entries with SL/TP RR and optional trailing stop (same logic as original script).",
    "params": {
        "start_date": {"type": "str", "default": "2023-01-01"},
        "end_date": {"type": "str", "default": "2025-01-01"},
        "pct_equity": {"type": "float", "default": 1.0, "min": 0.0, "max": 1.0},
        "rsi_len": {"type": "int", "default": 14, "min": 2, "max": 200},
        "long_th": {"type": "float", "default": 60.0},
        "short_th": {"type": "float", "default": 40.0},
        "tp_rr": {"type": "float", "default": 2.0, "min": 0.1, "max": 20.0},
        "entry_start": {"type": "str", "default": "12:30"},  # HH:MM
        "entry_end": {"type": "str", "default": "21:30"},    # HH:MM
        "trailing_stop": {"type": "float", "default": 0.0, "min": 0.0, "max": 0.2},
        "print_trades": {"type": "bool", "default": False},
    },
}

# ============================
# Optional Dashboard exporter
# ============================
DashboardExporter = None
try:
    from scripts.dashboard_exporter_updated import DashboardExporter  # type: ignore
except Exception:
    try:
        from scripts.dashboard_exporter import DashboardExporter  # type: ignore
    except Exception:
        DashboardExporter = None


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


def safe_mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def parse_date(s: str) -> pd.Timestamp:
    # Same behavior as your script: pandas parse, normalize to date
    return pd.to_datetime(s)


def to_ns(ts: pd.Timestamp) -> int:
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return int(ts.value)  # ns since epoch


def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def load_eurusd_csv(csv_path: str) -> pd.DataFrame:
    """
    SAME expectation as your script: columns include:
    date, time, open, high, low, close
    """
    df = pd.read_csv(csv_path)
    df = _normalize_cols(df)

    required = ["date", "time", "open", "high", "low", "close"]
    for c in required:
        if c not in df.columns:
            raise ValueError(f"Missing required column '{c}' in {csv_path}. Found: {list(df.columns)}")

    dt = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str), errors="coerce")
    if dt.isna().any():
        bad = df[dt.isna()].head(5)
        raise ValueError(
            "Failed to parse some DATE/TIME rows. Example bad rows:\n" + bad.to_string(index=False)
        )

    df["datetime"] = dt
    df = df.set_index("datetime").sort_index()

    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])
    return df[["open", "high", "low", "close"]]


# ============================
# CSV -> BIN (TickRecord 40B)
# ============================
# C++ TickRecord layout:
# uint64 timestamp; uint32 symbol_id; float price,bid,ask,bid_size,ask_size; uint32 volume; uint32 padding
TICK_STRUCT = struct.Struct("<QIfffffII")

def prepare_data(
    csv_paths: List[str],
    run_config: Dict[str, Any],
    asset: AssetSpec,
    out_bin_path: str,
    log: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Strategy-owned conversion (as you requested).
    Converts EURUSD M1 CSV -> TickRecord BIN.

    Note: BIN is not used by the pandas backtest logic, but it's generated
    as part of your pipeline contract (CSV -> BIN -> run).
    """
    if log is None:
        log = lambda s: None

    if not csv_paths:
        raise ValueError("No CSV files provided")

    csv_path = csv_paths[0]
    df_1m = load_eurusd_csv(csv_path)

    idx = df_1m.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")

    ts_ns = idx.view("int64")

    # Use CLOSE as price; build bid/ask using configured spread (if any)
    close = df_1m["close"].astype(np.float64).to_numpy()
    spread = float(getattr(asset, "spread", 0.0) or 0.0)
    bid = close - (spread / 2.0)
    ask = close + (spread / 2.0)

    symbol_id = int(asset.symbol_id)

    with open(out_bin_path, "wb") as f:
        for i in range(len(df_1m)):
            ts_u64 = int(ts_ns[i]) & 0xFFFFFFFFFFFFFFFF
            price_f = float(close[i])
            bid_f = float(bid[i])
            ask_f = float(ask[i])
            bid_size = 0.0
            ask_size = 0.0
            volume = 0
            padding = 0
            f.write(TICK_STRUCT.pack(ts_u64, symbol_id, price_f, bid_f, ask_f, bid_size, ask_size, volume, padding))
            
            if i % 100000 == 0:
                log(f"[BIN] Processed {i} / {len(df_1m)} rows ...")

    log(f"[BIN] Wrote {len(df_1m)} TickRecord rows -> {out_bin_path}")
    return out_bin_path


# ============================
# Strategy logic (UNCHANGED)
# ============================

def resample_to_5min(df_1m: pd.DataFrame) -> pd.DataFrame:
    df_5 = df_1m.resample("5min").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    ).dropna()
    return df_5


def rsi_wilder(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def in_time_window(ts: pd.Timestamp, start_t: dtime, end_t: dtime) -> bool:
    t = ts.time()
    return (t >= start_t) and (t <= end_t)


def compute_daily_equity_from_trade_pnls(
    trade_exits: pd.Series,
    trade_net_pnls: pd.Series,
    initial_capital: float,
) -> pd.DataFrame:
    """
    Same daily equity curve builder as your original script.
    """
    df = pd.DataFrame({"exit_time": pd.to_datetime(trade_exits), "net_pnl": trade_net_pnls.astype(float)})
    df["date"] = df["exit_time"].dt.floor("D")
    daily = df.groupby("date")["net_pnl"].sum().sort_index()

    equity = float(initial_capital)
    rows = []
    for d, pnl in daily.items():
        equity += float(pnl)
        rows.append({"date": d.strftime("%Y-%m-%d"), "total_equity": equity, "capital": float(initial_capital)})
    return pd.DataFrame(rows)


def sharpe_sortino_from_daily_equity(equity_curve: pd.DataFrame) -> Tuple[float, float]:
    if equity_curve.empty:
        return 0.0, 0.0
    eq = equity_curve["total_equity"].astype(float).values
    rets = np.diff(eq) / np.maximum(eq[:-1], 1e-12)
    if len(rets) < 2:
        return 0.0, 0.0
    mu = float(np.mean(rets))
    sd = float(np.std(rets, ddof=1))
    sharpe = (mu / sd) * np.sqrt(252.0) if sd > 0 else 0.0
    downside = rets[rets < 0]
    dd = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = (mu / dd) * np.sqrt(252.0) if dd > 0 else 0.0
    return sharpe, sortino


def max_drawdown_pct_from_daily_equity(equity_curve: pd.DataFrame) -> float:
    if equity_curve.empty:
        return 0.0
    eq = equity_curve["total_equity"].astype(float).values
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / np.maximum(peak, 1e-12)
    return float(np.min(dd) * 100.0)


def cagr_pct(initial_capital: float, final_equity: float, start_date: pd.Timestamp, end_date: pd.Timestamp) -> float:
    days = max((end_date - start_date).days, 1)
    years = days / 365.0
    if years <= 0:
        return 0.0
    return float(((final_equity / max(initial_capital, 1e-12)) ** (1.0 / years) - 1.0) * 100.0)


def run_rsi_timewindow_strategy(
    df_5m: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    initial_capital: float,
    commission_rate: float,
    pct_equity: float,
    rsi_len: int,
    long_th: float,
    short_th: float,
    tp_rr: float,
    entry_start: dtime,
    entry_end: dtime,
    trailing_stop_pct: float,
    print_trades: bool,
) -> pd.DataFrame:
    # SAME as your original script
    df = df_5m.loc[(df_5m.index >= start_date) & (df_5m.index <= end_date)].copy()
    if df.empty:
        return pd.DataFrame()

    df["rsi"] = rsi_wilder(df["close"], length=rsi_len)

    df["sig_long"] = df["rsi"] > long_th
    df["sig_short"] = df["rsi"] < short_th

    df["prev_low"] = df["low"].shift(1)
    df["prev_high"] = df["high"].shift(1)

    sig_low = df["low"].shift(1)
    sig_high = df["high"].shift(1)
    prev_low_of_sig = df["low"].shift(2)
    prev_high_of_sig = df["high"].shift(2)

    sl_long_on_entry_bar = np.minimum(sig_low, prev_low_of_sig)
    sl_short_on_entry_bar = np.minimum(sig_high, prev_high_of_sig)  # per your tightening rule

    df["act_long"] = df["sig_long"].shift(1)
    df["act_short"] = df["sig_short"].shift(1)
    df["sl_long"] = sl_long_on_entry_bar
    df["sl_short"] = sl_short_on_entry_bar

    equity = float(initial_capital)

    position = 0
    entry_price = 0.0
    entry_time = None
    qty = 0.0
    sl = 0.0
    tp = 0.0

    trail_high = None
    trail_low = None

    trades = []
    idx_list = list(df.index)

    for i in range(len(df)):
        ts = idx_list[i]
        row = df.iloc[i]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])

        # EXIT (intrabar)
        if position != 0:
            effective_sl = sl
            if trailing_stop_pct > 0:
                if position == 1:
                    trail_high = h if trail_high is None else max(trail_high, h)
                    tr_sl = trail_high * (1.0 - trailing_stop_pct)
                    effective_sl = max(effective_sl, tr_sl)
                else:
                    trail_low = l if trail_low is None else min(trail_low, l)
                    tr_sl = trail_low * (1.0 + trailing_stop_pct)
                    effective_sl = min(effective_sl, tr_sl)

            exit_reason = None
            exit_price = None

            if position == 1:
                if l <= effective_sl:
                    exit_reason = "StopLoss/Trail"
                    exit_price = o if o < effective_sl else effective_sl
                elif h >= tp:
                    exit_reason = "TakeProfit"
                    exit_price = o if o > tp else tp
            else:
                if h >= effective_sl:
                    exit_reason = "StopLoss/Trail"
                    exit_price = o if o > effective_sl else effective_sl
                elif l <= tp:
                    exit_reason = "TakeProfit"
                    exit_price = o if o < tp else tp

            if exit_price is not None:
                if position == 1:
                    gross = (exit_price - entry_price) * qty
                else:
                    gross = (entry_price - exit_price) * qty

                entry_comm = entry_price * qty * commission_rate
                exit_comm = exit_price * qty * commission_rate
                comm = entry_comm + exit_comm
                net = gross - comm
                equity += net

                trades.append(
                    {
                        "side": "LONG" if position == 1 else "SHORT",
                        "entry_time": entry_time,
                        "exit_time": ts,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "qty": qty,
                        "gross_pnl": gross,
                        "commission": comm,
                        "net_pnl": net,
                        "equity": equity,
                        "reason": exit_reason,
                        "sl_init": sl,
                        "tp": tp,
                    }
                )

                if print_trades:
                    print(
                        f"[EXIT] {ts} {('LONG' if position==1 else 'SHORT')} "
                        f"exit={exit_price:.5f} reason={exit_reason} net={net:.2f} eq={equity:.2f}"
                    )

                position = 0
                entry_price = 0.0
                entry_time = None
                qty = 0.0
                sl = 0.0
                tp = 0.0
                trail_high = None
                trail_low = None

        # ENTRY (next bar open)
        if position == 0 and equity > 0:
            if not in_time_window(ts, entry_start, entry_end):
                continue

            if pd.isna(row["sl_long"]) or pd.isna(row["sl_short"]):
                continue

            if row["act_long"] is True:
                entry = o
                sl_candidate = float(row["sl_long"])
                if sl_candidate >= entry:
                    continue
                risk = entry - sl_candidate
                target = entry + tp_rr * risk
                alloc = equity * pct_equity
                qty_ = alloc / entry

                position = 1
                entry_price = entry
                entry_time = ts
                qty = qty_
                sl = sl_candidate
                tp = target
                trail_high = entry
                trail_low = None

                if print_trades:
                    print(f"[ENTRY] {ts} LONG entry={entry_price:.5f} sl={sl:.5f} tp={tp:.5f} qty={qty:.4f} eq={equity:.2f}")

            elif row["act_short"] is True:
                entry = o
                sl_candidate = float(row["sl_short"])
                if sl_candidate <= entry:
                    continue
                risk = sl_candidate - entry
                target = entry - tp_rr * risk
                alloc = equity * pct_equity
                qty_ = alloc / entry

                position = -1
                entry_price = entry
                entry_time = ts
                qty = qty_
                sl = sl_candidate
                tp = target
                trail_low = entry
                trail_high = None

                if print_trades:
                    print(f"[ENTRY] {ts} SHORT entry={entry_price:.5f} sl={sl:.5f} tp={tp:.5f} qty={qty:.4f} eq={equity:.2f}")

    return pd.DataFrame(trades)


def export_csvs_and_dashboard(
    out_dir: str,
    basket_summary: pd.DataFrame,
    trade_log: pd.DataFrame,
    equity_curve: pd.DataFrame,
    initial_capital: float,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    if log is None:
        log = print
    safe_mkdir(out_dir)

    bs_path = os.path.join(out_dir, "basket_summary.csv")
    tl_path = os.path.join(out_dir, "trade_log.csv")
    eq_path = os.path.join(out_dir, "equity_curve.csv")

    basket_summary.to_csv(bs_path, index=False)
    trade_log.to_csv(tl_path, index=False)
    equity_curve.to_csv(eq_path, index=False)

    log(f"[CSV] basket_summary -> {bs_path}")
    log(f"[CSV] trade_log      -> {tl_path}")
    log(f"[CSV] equity_curve   -> {eq_path}")

    # [FIX] Strategy writes its own CSVs above.
    # We do NOT want to use the generic DashboardExporter to overwrite them
    # because the generic exporter might produce inferior or empty results.
    log(f"[DEBUG] CSVs handled by strategy native export. Skipping DashboardExporter.")
    return

def run_pipeline(
    csv_paths: List[str],
    run_config: Dict[str, Any],
    asset: AssetSpec,
    out_dir: str,
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, str]:
    """
    This is the function your local runner API should call.
    It does:
    1) CSV -> BIN (inside strategy)
    2) pandas backtest (same logic)
    3) exports dashboard CSVs
    Returns dict of output file paths.
    """
    if log is None:
        log = print

    # Initialize params from run_config or defaults
    params = run_config.get("params", {}).copy()
    
    # Fill missing with defaults from META
    for k, v in STRATEGY_META.get("params", {}).items():
        if k not in params:
            params[k] = v.get("default")

    # MERGE: run_config top-level keys should override/augment params for dashboard compatibility
    # [FIX] Iterate over ALL defined params, not just a hardcoded list
    for k in STRATEGY_META.get("params", {}).keys():
        if k in run_config:
            params[k] = run_config[k]

    log(f"[DEBUG] Final Strategy Params: {params}")

    today = pd.Timestamp.now()
    
    # 1. Determine End Date: Use params["end_date"] if present, else Today
    # 1. Determine End Date:
    user_params = run_config.get("params", {})
    if "end_date" in user_params:
        end_date = parse_date(user_params["end_date"])
    elif "years" in run_config:
        # If using 'years' horizon, default end date to NOW (so we look back from today)
        end_date = pd.Timestamp.now()
    else:
        # Fallback to params (which includes defaults)
        end_date = parse_date(params.get("end_date", "2025-01-01"))

    # 2. Determine Start Date:
    if "start_date" in user_params:
        start_date = parse_date(user_params["start_date"])
    elif "years" in run_config:
        years_horizon = float(run_config.get("years", 2.0))
        days_horizon = int(years_horizon * 365)
        start_date = end_date - pd.Timedelta(days=days_horizon)
        log(f"[DEBUG] Using Data Horizon: {years_horizon} years -> {start_date.date()} to {end_date.date()}")
    else:
        start_date = parse_date(params.get("start_date", "2023-01-01"))
    
    log(f"[DEBUG] Date Range: {start_date} -> {end_date}")

    initial_capital = float(run_config.get("initial_capital", 10_000.0))
    commission_rate = float(run_config.get("commission_rate", 0.0002))

    pct_equity = float(params.get("pct_equity", 1.0))
    rsi_len = int(params.get("rsi_len", 14))
    long_th = float(params.get("long_th", 60.0))
    short_th = float(params.get("short_th", 40.0))
    tp_rr = float(params.get("tp_rr", 2.0))

    entry_start_s = str(params.get("entry_start", "12:30"))
    entry_end_s = str(params.get("entry_end", "21:30"))
    entry_start = dtime.fromisoformat(entry_start_s)
    entry_end = dtime.fromisoformat(entry_end_s)

    trailing_stop_pct = float(params.get("trailing_stop", 0.0))
    print_trades = bool(params.get("print_trades", False))
    
    log(f"Step 1/3: Converting CSV -> BIN (strategy side) ...")
    bin_path = os.path.join(out_dir, "data_tickrecord.bin")
    prepare_data(csv_paths, run_config, asset, bin_path, log=log)

    log("Step 2/3: Running RSI backtest ...")
    df_1m = load_eurusd_csv(csv_paths[0])
    df_5m = resample_to_5min(df_1m)

    trades = run_rsi_timewindow_strategy(
        df_5m=df_5m,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        commission_rate=commission_rate,
        pct_equity=pct_equity,
        rsi_len=rsi_len,
        long_th=long_th,
        short_th=short_th,
        tp_rr=tp_rr,
        entry_start=entry_start,
        entry_end=entry_end,
        trailing_stop_pct=trailing_stop_pct,
        print_trades=print_trades,
    )

    if trades.empty:
        # still export empty CSVs so dashboard doesn't crash
        basket_summary = pd.DataFrame([])
        trade_log = pd.DataFrame([])
        equity_curve = pd.DataFrame([])
        export_csvs_and_dashboard(out_dir, basket_summary, trade_log, equity_curve, initial_capital, log=log)
        log("Backtest finished (no trades).")
        return {
            "basket_summary": os.path.join(out_dir, "basket_summary.csv"),
            "trade_log": os.path.join(out_dir, "trade_log.csv"),
            "equity_curve": os.path.join(out_dir, "equity_curve.csv"),
        }

    # ============================
    # Build basket_summary.csv (same as your script)
    # ============================
    basket_summary = trades.copy()
    basket_summary["duration_minutes"] = (
        (pd.to_datetime(basket_summary["exit_time"]) - pd.to_datetime(basket_summary["entry_time"]))
        .dt.total_seconds()
        / 60.0
    )
    basket_summary["date"] = pd.to_datetime(basket_summary["entry_time"]).dt.strftime("%Y-%m-%d")
    basket_summary = basket_summary.reset_index(drop=True)
    basket_summary.insert(0, "basket_id", np.arange(1, len(basket_summary) + 1))

    # ============================
    # Build trade_log.csv (same as your script: entry+exit rows)
    # ============================
    tl_rows = []
    for _, row in basket_summary.iterrows():
        et = pd.to_datetime(row["entry_time"])
        xt = pd.to_datetime(row["exit_time"])
        side = str(row["side"])

        tl_rows.append(
            {
                "timestamp": to_ns(et),
                "price": float(row["entry_price"]),
                "size": float(row["qty"]),
                "type": "entry",
                "strategy": f"RSI_{side}",
                "pnl": 0.0,
            }
        )
        tl_rows.append(
            {
                "timestamp": to_ns(xt),
                "price": float(row["exit_price"]),
                "size": float(row["qty"]),
                "type": "exit",
                "strategy": f"RSI_{side}",
                "pnl": float(row["net_pnl"]),
            }
        )
    trade_log = pd.DataFrame(tl_rows).sort_values("timestamp").reset_index(drop=True)

    # ============================
    # Build equity_curve.csv (same as your script)
    # ============================
    eq_df = compute_daily_equity_from_trade_pnls(
        trade_exits=trades["exit_time"],
        trade_net_pnls=trades["net_pnl"],
        initial_capital=initial_capital,
    )

    export_csvs_and_dashboard(out_dir, basket_summary, trade_log, eq_df, initial_capital, log=log)

    final_equity = float(eq_df["total_equity"].iloc[-1]) if not eq_df.empty else initial_capital
    sharpe, sortino = sharpe_sortino_from_daily_equity(eq_df)
    mdd = max_drawdown_pct_from_daily_equity(eq_df)
    cagr = cagr_pct(initial_capital, final_equity, start_date, end_date)

    log(f"Backtest finished. Final equity={final_equity:.2f} | Sharpe={sharpe:.2f} | Sortino={sortino:.2f} | MDD={mdd:.2f}% | CAGR={cagr:.2f}%")

    return {
        "basket_summary": os.path.join(out_dir, "basket_summary.csv"),
        "trade_log": os.path.join(out_dir, "trade_log.csv"),
        "equity_curve": os.path.join(out_dir, "equity_curve.csv"),
        "bin_path": os.path.join(out_dir, "data_tickrecord.bin"),
    }


# ============================
# Prototype StrategyImpl class
# ============================
class StrategyImpl(Strategy):
    """
    Required by prototype.py contract.
    For this RSI strategy, execution is handled by run_pipeline() (pandas backtest).
    The UI runner should call run_pipeline() directly.
    """

    def __init__(self, engine: Any, portfolio: Any, risk_engine: Any, run_config: Dict[str, Any], asset_spec: AssetSpec):
        super().__init__()
        self.engine = engine
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        self.run_config = run_config
        self.asset = asset_spec

        self.equity_curve: List[float] = []
        self.trades: List[Dict[str, Any]] = []

    def on_start(self) -> None:
        # This strategy is intended to run via run_pipeline() in the runner.
        pass

    def on_tick(self, tick: Any) -> None:
        pass

    def on_bar(self, bar: Any) -> None:
        pass

    def on_fill(self, fill: Any) -> None:
        pass

    def on_end(self) -> None:
        pass

