#!/usr/bin/env python3
"""
bt_reference_runner.py

Goal:
- Produce a "Backtrader reference" output that is directly comparable to combined_backtest.py.
- Uses Backtrader as the event loop (1m iteration), BUT uses the SAME execution / fill model
  as combined_backtest.py (manual fills), so results match closely.

Outputs (written under results/backtrader_reference/):
- strategy1_trades_log.csv
- strategy2_trades_log.csv
- strategy1_summary.json
- strategy2_summary.json
- combined_summary.json

Run:
  python3 scripts/bt_reference_runner.py
"""

import os
import json
import math
import pandas as pd
import numpy as np
import backtrader as bt

# ============================================================
# CONFIG (MATCH combined_backtest.py)
# ============================================================
CSV_FILE_PATH = "/mnt/c/Users/spkri/OneDrive/Desktop/Python/reliance_1m.csv"
START_DATE = "2023-01-01"
END_DATE = "2024-12-31"

INITIAL_CAPITAL = 10000.0
COMMISSION_RATE = 0.0002  # 0.02%

ENABLE_STRATEGY_1 = True
ENABLE_STRATEGY_2 = True

# Strategy 1 (BB)
S1_PCT_EQUITY = 0.5
S1_LENGTH = 20
S1_MULT = 2.5
S1_DIRECTION = 0  # 0 both, 1 long only, -1 short only

# Strategy 2 (3EMA+ATR)
S2_PCT_EQUITY = 0.1
S2_SLOW_EMA_LEN = 30
S2_MID_EMA_LEN = 12
S2_FAST_EMA_LEN = 7
S2_ATR_LEN = 7
S2_TP_ATR_MULT = 4
S2_SL_ATR_MULT = 1

OUT_DIR = os.path.join("results", "backtrader_reference")
os.makedirs(OUT_DIR, exist_ok=True)


# ============================================================
# HELPERS (MATCH combined_backtest.py)
# ============================================================
def load_and_prep_data(filepath: str) -> pd.DataFrame:
    print(f"[BT-REF] Loading data from {filepath} ...")
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip().str.lower()

    if "timestamp" in df.columns:
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    elif "date" in df.columns:
        df["datetime"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    elif "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    else:
        raise ValueError("Could not find 'timestamp', 'date', or 'datetime' column")

    df = df.dropna(subset=["datetime"])
    df = df.set_index("datetime").sort_index()

    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)

    for c in ["open", "high", "low", "close"]:
        if c not in df.columns:
            raise ValueError(f"Missing required column: {c}")

    mask = (df.index >= START_DATE) & (df.index <= END_DATE)
    df = df.loc[mask].copy()

    print(f"[BT-REF] Loaded {len(df)} rows: {df.index[0]} -> {df.index[-1]}")
    return df


def calculate_rma(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(alpha=1 / length, adjust=False).mean()


# ============================================================
# STRATEGY 1 SIGNAL PREP (IDENTICAL)
# ============================================================
def prep_strategy1_signals(df_1m: pd.DataFrame) -> pd.DataFrame:
    df_45m = df_1m.resample("45min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()

    if len(df_45m) < S1_LENGTH:
        return pd.DataFrame()

    df_45m["sma"] = df_45m["close"].rolling(window=S1_LENGTH).mean()
    df_45m["std"] = df_45m["close"].rolling(window=S1_LENGTH).std()
    df_45m["upper"] = df_45m["sma"] + (S1_MULT * df_45m["std"])
    df_45m["lower"] = df_45m["sma"] - (S1_MULT * df_45m["std"])

    df_45m["prev_close"] = df_45m["close"].shift(1)
    df_45m["prev_lower"] = df_45m["lower"].shift(1)
    df_45m["prev_upper"] = df_45m["upper"].shift(1)

    df_45m["long_signal"] = (df_45m["prev_close"] < df_45m["prev_lower"]) & (
        df_45m["close"] > df_45m["lower"]
    )
    df_45m["short_signal"] = (df_45m["prev_close"] > df_45m["prev_upper"]) & (
        df_45m["close"] < df_45m["upper"]
    )

    df_45m["active_long_signal"] = df_45m["long_signal"].shift(1)
    df_45m["active_short_signal"] = df_45m["short_signal"].shift(1)
    df_45m["entry_stop_lower"] = df_45m["lower"].shift(1)
    df_45m["entry_stop_upper"] = df_45m["upper"].shift(1)

    cols = ["active_long_signal", "active_short_signal", "entry_stop_lower", "entry_stop_upper"]
    aligned = df_45m[cols].reindex(df_1m.index, method="ffill")
    out = df_1m.join(aligned)

    out["active_long_signal"] = out["active_long_signal"].fillna(False).astype(bool)
    out["active_short_signal"] = out["active_short_signal"].fillna(False).astype(bool)

    return out


# ============================================================
# STRATEGY 2 SIGNAL PREP (IDENTICAL)
# ============================================================
def prep_strategy2_signals(df_1m: pd.DataFrame) -> pd.DataFrame:
    df_45m = df_1m.resample("45min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()

    if len(df_45m) < S2_SLOW_EMA_LEN:
        return pd.DataFrame()

    df_45m["ema_fast"] = df_45m["close"].ewm(span=S2_FAST_EMA_LEN, adjust=False).mean()
    df_45m["ema_mid"] = df_45m["close"].ewm(span=S2_MID_EMA_LEN, adjust=False).mean()
    df_45m["ema_slow"] = df_45m["close"].ewm(span=S2_SLOW_EMA_LEN, adjust=False).mean()

    df_45m["prev_close"] = df_45m["close"].shift(1)
    df_45m["tr1"] = df_45m["high"] - df_45m["low"]
    df_45m["tr2"] = (df_45m["high"] - df_45m["prev_close"]).abs()
    df_45m["tr3"] = (df_45m["low"] - df_45m["prev_close"]).abs()
    df_45m["tr"] = df_45m[["tr1", "tr2", "tr3"]].max(axis=1)
    df_45m["atr"] = calculate_rma(df_45m["tr"], S2_ATR_LEN)

    df_45m["prev_ema_mid"] = df_45m["ema_mid"].shift(1)
    df_45m["prev_ema_slow"] = df_45m["ema_slow"].shift(1)
    df_45m["prev_ema_fast"] = df_45m["ema_fast"].shift(1)

    df_45m["long_entry_signal"] = (df_45m["prev_ema_mid"] <= df_45m["prev_ema_slow"]) & (
        df_45m["ema_mid"] > df_45m["ema_slow"]
    )
    df_45m["exit_signal"] = (df_45m["prev_ema_fast"] >= df_45m["prev_ema_mid"]) & (
        df_45m["ema_fast"] < df_45m["ema_mid"]
    )

    df_45m["signal_id"] = df_45m.index.view("int64")

    df_45m["active_entry_signal"] = df_45m["long_entry_signal"].shift(1)
    df_45m["active_exit_signal"] = df_45m["exit_signal"].shift(1)
    df_45m["active_signal_id"] = df_45m["signal_id"].shift(1)

    df_45m["signal_bar_close"] = df_45m["close"].shift(1)
    df_45m["signal_bar_atr"] = df_45m["atr"].shift(1)

    cols = [
        "active_entry_signal",
        "active_exit_signal",
        "signal_bar_close",
        "signal_bar_atr",
        "active_signal_id",
    ]
    aligned = df_45m[cols].reindex(df_1m.index, method="ffill")
    out = df_1m.join(aligned)

    out["active_entry_signal"] = out["active_entry_signal"].fillna(False).astype(bool)
    out["active_exit_signal"] = out["active_exit_signal"].fillna(False).astype(bool)

    for c in ["signal_bar_close", "signal_bar_atr", "active_signal_id"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")

    return out


# ============================================================
# BACKTRADER DATA FEEDS (EXTRA COLUMNS)
# ============================================================
class PandasDataS1(bt.feeds.PandasData):
    lines = ("active_long_signal", "active_short_signal", "entry_stop_lower", "entry_stop_upper")
    params = (
        ("datetime", None),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", -1),
        ("openinterest", -1),
        ("active_long_signal", "active_long_signal"),
        ("active_short_signal", "active_short_signal"),
        ("entry_stop_lower", "entry_stop_lower"),
        ("entry_stop_upper", "entry_stop_upper"),
    )


class PandasDataS2(bt.feeds.PandasData):
    lines = (
        "active_entry_signal",
        "active_exit_signal",
        "signal_bar_close",
        "signal_bar_atr",
        "active_signal_id",
    )
    params = (
        ("datetime", None),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", -1),
        ("openinterest", -1),
        ("active_entry_signal", "active_entry_signal"),
        ("active_exit_signal", "active_exit_signal"),
        ("signal_bar_close", "signal_bar_close"),
        ("signal_bar_atr", "signal_bar_atr"),
        ("active_signal_id", "active_signal_id"),
    )


# ============================================================
# STRATEGY 1 "BT-REF" (MANUAL FILLS = combined_backtest.py)
# ============================================================
class Strategy1BB_Ref(bt.Strategy):
    def __init__(self):
        self.position_state = 0  # 0 flat, 1 long, -1 short
        self.entry_price = 0.0
        self.entry_time = None
        self.qty = 0.0
        self.equity = INITIAL_CAPITAL
        self.trades = []

        self.bankrupt = False  # NEW

    def next(self):
        if self.bankrupt:
            return

        if self.equity <= 0:
            self.equity = 0.0
            self.bankrupt = True
            self.position_state = 0
            self.qty = 0.0
            return

        dt = self.data.datetime.datetime(0)
        o = float(self.data.open[0])
        h = float(self.data.high[0])
        l = float(self.data.low[0])

        entry_stop_lower = float(self.data.entry_stop_lower[0]) if not math.isnan(float(self.data.entry_stop_lower[0])) else np.nan
        entry_stop_upper = float(self.data.entry_stop_upper[0]) if not math.isnan(float(self.data.entry_stop_upper[0])) else np.nan

        if np.isnan(entry_stop_lower) or np.isnan(entry_stop_upper):
            return

        allow_long = (S1_DIRECTION == 0) or (S1_DIRECTION == 1)
        allow_short = (S1_DIRECTION == 0) or (S1_DIRECTION == -1)

        active_long = bool(self.data.active_long_signal[0])
        active_short = bool(self.data.active_short_signal[0])

        if active_long and allow_long and self.equity > 0:
            stop_price = entry_stop_lower
            fill_price = None

            if o >= stop_price:
                fill_price = o
            elif h >= stop_price:
                fill_price = stop_price

            if fill_price is not None:
                if self.position_state == -1:
                    gross_pnl = (self.entry_price - fill_price) * self.qty
                    entry_comm = self.entry_price * self.qty * COMMISSION_RATE
                    exit_comm = fill_price * self.qty * COMMISSION_RATE
                    total_comm = entry_comm + exit_comm
                    net_pnl = gross_pnl - total_comm
                    self.equity += net_pnl

                    if self.equity <= 0:
                        self.equity = 0.0
                        self.bankrupt = True

                    self.trades.append(
                        dict(
                            type="Short",
                            entry_time=self.entry_time,
                            exit_time=dt,
                            entry_price=self.entry_price,
                            exit_price=fill_price,
                            qty=self.qty,
                            gross_pnl=gross_pnl,
                            commission=total_comm,
                            net_pnl=net_pnl,
                            equity=self.equity,
                        )
                    )
                    self.position_state = 0
                    self.qty = 0.0

                    if self.bankrupt:
                        return

                if self.position_state == 0 and self.equity > 0:
                    self.position_state = 1
                    self.entry_price = fill_price
                    self.entry_time = dt
                    alloc = self.equity * S1_PCT_EQUITY
                    self.qty = alloc / fill_price

        elif active_short and allow_short and self.equity > 0:
            stop_price = entry_stop_upper
            fill_price = None

            if o <= stop_price:
                fill_price = o
            elif l <= stop_price:
                fill_price = stop_price

            if fill_price is not None:
                if self.position_state == 1:
                    gross_pnl = (fill_price - self.entry_price) * self.qty
                    entry_comm = self.entry_price * self.qty * COMMISSION_RATE
                    exit_comm = fill_price * self.qty * COMMISSION_RATE
                    total_comm = entry_comm + exit_comm
                    net_pnl = gross_pnl - total_comm
                    self.equity += net_pnl

                    if self.equity <= 0:
                        self.equity = 0.0
                        self.bankrupt = True

                    self.trades.append(
                        dict(
                            type="Long",
                            entry_time=self.entry_time,
                            exit_time=dt,
                            entry_price=self.entry_price,
                            exit_price=fill_price,
                            qty=self.qty,
                            gross_pnl=gross_pnl,
                            commission=total_comm,
                            net_pnl=net_pnl,
                            equity=self.equity,
                        )
                    )
                    self.position_state = 0
                    self.qty = 0.0

                    if self.bankrupt:
                        return

                if self.position_state == 0 and self.equity > 0:
                    self.position_state = -1
                    self.entry_price = fill_price
                    self.entry_time = dt
                    alloc = self.equity * S1_PCT_EQUITY
                    self.qty = alloc / fill_price

    def stop(self):
        if self.bankrupt:
            return
        if len(self.data) == 0:
            return
        last_dt = self.data.datetime.datetime(-1)
        last_close = float(self.data.close[-1])

        if self.position_state != 0:
            if self.position_state == 1:
                gross_pnl = (last_close - self.entry_price) * self.qty
                entry_comm = self.entry_price * self.qty * COMMISSION_RATE
                exit_comm = last_close * self.qty * COMMISSION_RATE
                total_comm = entry_comm + exit_comm
                net_pnl = gross_pnl - total_comm
                self.equity += net_pnl
                if self.equity <= 0:
                    self.equity = 0.0

                self.trades.append(
                    dict(
                        type="Long (End)",
                        entry_time=self.entry_time,
                        exit_time=last_dt,
                        entry_price=self.entry_price,
                        exit_price=last_close,
                        qty=self.qty,
                        gross_pnl=gross_pnl,
                        commission=total_comm,
                        net_pnl=net_pnl,
                        equity=self.equity,
                    )
                )
            elif self.position_state == -1:
                gross_pnl = (self.entry_price - last_close) * self.qty
                entry_comm = self.entry_price * self.qty * COMMISSION_RATE
                exit_comm = last_close * self.qty * COMMISSION_RATE
                total_comm = entry_comm + exit_comm
                net_pnl = gross_pnl - total_comm
                self.equity += net_pnl
                if self.equity <= 0:
                    self.equity = 0.0

                self.trades.append(
                    dict(
                        type="Short (End)",
                        entry_time=self.entry_time,
                        exit_time=last_dt,
                        entry_price=self.entry_price,
                        exit_price=last_close,
                        qty=self.qty,
                        gross_pnl=gross_pnl,
                        commission=total_comm,
                        net_pnl=net_pnl,
                        equity=self.equity,
                    )
                )


# ============================================================
# STRATEGY 2 "BT-REF" (MANUAL FILLS = combined_backtest.py)
# ============================================================
class Strategy23EMAATR_Ref(bt.Strategy):
    def __init__(self):
        self.position_state = 0  # 0 flat, 1 long
        self.entry_price = 0.0
        self.entry_time = None
        self.qty = 0.0
        self.equity = INITIAL_CAPITAL

        self.tp = 0.0
        self.sl = 0.0
        self.last_traded_signal_id = None

        self.trades = []
        self.equity_curve = []

        self.bankrupt = False  # NEW

    def next(self):
        dt = self.data.datetime.datetime(0)
        o = float(self.data.open[0])
        h = float(self.data.high[0])
        l = float(self.data.low[0])
        c = float(self.data.close[0])

        # Floating equity mark-to-market (identical)
        floating_equity = self.equity
        if self.position_state == 1:
            floating_equity = self.equity + (c - self.entry_price) * self.qty

        self.equity_curve.append({"time": dt, "equity": max(floating_equity, 0.0)})

        if self.bankrupt:
            return

        # NEW: margin call using floating equity
        if self.position_state == 1 and floating_equity <= 0:
            exit_reason = "Margin Call"
            exit_price = c

            gross_pnl = (exit_price - self.entry_price) * self.qty
            entry_comm = self.entry_price * self.qty * COMMISSION_RATE
            exit_comm = exit_price * self.qty * COMMISSION_RATE
            total_comm = entry_comm + exit_comm
            net_pnl = gross_pnl - total_comm
            self.equity += net_pnl

            if self.equity <= 0:
                self.equity = 0.0
                self.bankrupt = True

            self.trades.append(
                dict(
                    type="Long",
                    reason=exit_reason,
                    entry_time=self.entry_time,
                    exit_time=dt,
                    entry_price=self.entry_price,
                    exit_price=exit_price,
                    qty=self.qty,
                    gross_pnl=gross_pnl,
                    commission=total_comm,
                    net_pnl=net_pnl,
                    equity=self.equity,
                )
            )

            self.position_state = 0
            self.qty = 0.0
            self.entry_price = 0.0
            self.entry_time = None
            return

        if self.equity <= 0:
            self.equity = 0.0
            self.bankrupt = True
            self.position_state = 0
            self.qty = 0.0
            return

        atr = float(self.data.signal_bar_atr[0]) if not math.isnan(float(self.data.signal_bar_atr[0])) else np.nan
        ref_close = float(self.data.signal_bar_close[0]) if not math.isnan(float(self.data.signal_bar_close[0])) else np.nan
        active_entry = bool(self.data.active_entry_signal[0])
        active_exit = bool(self.data.active_exit_signal[0])
        sig_id = float(self.data.active_signal_id[0]) if not math.isnan(float(self.data.active_signal_id[0])) else np.nan

        if np.isnan(atr) or np.isnan(ref_close):
            return

        # 1) EXIT LOGIC
        if self.position_state == 1:
            exit_reason = None
            exit_price = None

            if l <= self.sl:
                exit_reason = "Stop Loss"
                exit_price = self.sl
                if o < self.sl:
                    exit_price = o

            elif h >= self.tp:
                exit_reason = "Take Profit"
                exit_price = self.tp
                if o > self.tp:
                    exit_price = o

            elif active_exit:
                exit_reason = "EMA Cross Exit"
                exit_price = o

            if exit_price is not None:
                gross_pnl = (exit_price - self.entry_price) * self.qty
                entry_comm = self.entry_price * self.qty * COMMISSION_RATE
                exit_comm = exit_price * self.qty * COMMISSION_RATE
                total_comm = entry_comm + exit_comm
                net_pnl = gross_pnl - total_comm
                self.equity += net_pnl

                if self.equity <= 0:
                    self.equity = 0.0
                    self.bankrupt = True

                self.trades.append(
                    dict(
                        type="Long",
                        reason=exit_reason,
                        entry_time=self.entry_time,
                        exit_time=dt,
                        entry_price=self.entry_price,
                        exit_price=exit_price,
                        qty=self.qty,
                        gross_pnl=gross_pnl,
                        commission=total_comm,
                        net_pnl=net_pnl,
                        equity=self.equity,
                    )
                )

                self.position_state = 0
                self.qty = 0.0
                self.entry_price = 0.0
                self.entry_time = None

                if self.bankrupt:
                    return

        # 2) ENTRY LOGIC
        if self.position_state == 0 and (not self.bankrupt) and self.equity > 0:
            if active_entry:
                if (not np.isnan(sig_id)) and (sig_id != self.last_traded_signal_id):
                    self.position_state = 1
                    self.entry_price = o
                    self.entry_time = dt
                    self.last_traded_signal_id = sig_id

                    alloc = self.equity * S2_PCT_EQUITY
                    self.qty = alloc / self.entry_price

                    self.tp = ref_close + (atr * S2_TP_ATR_MULT)
                    self.sl = ref_close - (atr * S2_SL_ATR_MULT)

    def stop(self):
        if self.bankrupt:
            return
        if len(self.data) == 0:
            return
        last_dt = self.data.datetime.datetime(-1)
        last_close = float(self.data.close[-1])

        if self.position_state == 1:
            gross_pnl = (last_close - self.entry_price) * self.qty
            entry_comm = self.entry_price * self.qty * COMMISSION_RATE
            exit_comm = last_close * self.qty * COMMISSION_RATE
            total_comm = entry_comm + exit_comm
            net_pnl = gross_pnl - total_comm
            self.equity += net_pnl
            if self.equity <= 0:
                self.equity = 0.0

            self.trades.append(
                dict(
                    type="Long (End)",
                    reason="Backtest End",
                    entry_time=self.entry_time,
                    exit_time=last_dt,
                    entry_price=self.entry_price,
                    exit_price=last_close,
                    qty=self.qty,
                    gross_pnl=gross_pnl,
                    commission=total_comm,
                    net_pnl=net_pnl,
                    equity=self.equity,
                )
            )


# ============================================================
# METRICS (SAME STYLE AS Felix/combined)
# ============================================================
def summarize_trades(trades_df: pd.DataFrame, label: str, initial_capital: float) -> dict:
    if trades_df.empty:
        return {
            "label": label,
            "initial_capital": initial_capital,
            "final_equity": initial_capital,
            "net_pnl": 0.0,
            "num_trades": 0,
            "commission_rate": COMMISSION_RATE,
            "start_date": START_DATE,
            "end_date": END_DATE,
        }
    final_equity = float(trades_df.iloc[-1]["equity"])
    net_pnl = final_equity - initial_capital
    return {
        "label": label,
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "net_pnl": net_pnl,
        "num_trades": int(len(trades_df)),
        "total_commission": float(trades_df["commission"].sum()) if "commission" in trades_df.columns else 0.0,
        "commission_rate": COMMISSION_RATE,
        "start_date": START_DATE,
        "end_date": END_DATE,
    }


def combined_summary(s1: dict, s2: dict) -> dict:
    combined_net = float(s1["net_pnl"]) + float(s2["net_pnl"])
    return {
        "initial_capital": INITIAL_CAPITAL,
        "strategy1_final_equity": s1["final_equity"],
        "strategy2_final_equity": s2["final_equity"],
        "strategy1_net_pnl": s1["net_pnl"],
        "strategy2_net_pnl": s2["net_pnl"],
        "combined_net_pnl": combined_net,
        "combined_final_equity": INITIAL_CAPITAL + combined_net,
        "strategy1_trades": s1["num_trades"],
        "strategy2_trades": s2["num_trades"],
        "combined_trades": int(s1["num_trades"]) + int(s2["num_trades"]),
        "commission_rate": COMMISSION_RATE,
        "start_date": START_DATE,
        "end_date": END_DATE,
    }


def print_block(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def fmt_money(x):
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return str(x)


def print_summary(name: str, s: dict):
    print_block(f"BACKTRADER-REF RESULTS - {name}")
    print(f"Initial Capital:   {fmt_money(s.get('initial_capital'))}")
    print(f"Final Equity:      {fmt_money(s.get('final_equity'))}")
    print(f"Net PnL:           {fmt_money(s.get('net_pnl'))}")
    print(f"Total Trades:      {s.get('num_trades')}")
    if "total_commission" in s:
        print(f"Total Commission:  {fmt_money(s.get('total_commission'))}")
    print(f"Commission Rate:   {s.get('commission_rate')}")
    print(f"Start Date:        {s.get('start_date')}")
    print(f"End Date:          {s.get('end_date')}")


# ============================================================
# RUNNERS
# ============================================================
def run_bt_ref_strategy1(df_s1: pd.DataFrame):
    cerebro = bt.Cerebro(stdstats=False)
    data = PandasDataS1(dataname=df_s1)
    cerebro.adddata(data)
    cerebro.addstrategy(Strategy1BB_Ref)
    cerebro.broker.setcash(INITIAL_CAPITAL)

    strat = cerebro.run()[0]
    trades_df = pd.DataFrame(strat.trades)

    out_csv = os.path.join(OUT_DIR, "strategy1_trades_log.csv")
    trades_df.to_csv(out_csv, index=False)

    s1_sum = summarize_trades(trades_df, "STRATEGY 1 (BB)", INITIAL_CAPITAL)
    out_json = os.path.join(OUT_DIR, "strategy1_summary.json")
    with open(out_json, "w") as f:
        json.dump(s1_sum, f, indent=2, default=str)

    return trades_df, s1_sum


def run_bt_ref_strategy2(df_s2: pd.DataFrame):
    cerebro = bt.Cerebro(stdstats=False)
    data = PandasDataS2(dataname=df_s2)
    cerebro.adddata(data)
    cerebro.addstrategy(Strategy23EMAATR_Ref)
    cerebro.broker.setcash(INITIAL_CAPITAL)

    strat = cerebro.run()[0]
    trades_df = pd.DataFrame(strat.trades)
    equity_df = pd.DataFrame(strat.equity_curve)

    out_csv = os.path.join(OUT_DIR, "strategy2_trades_log.csv")
    trades_df.to_csv(out_csv, index=False)
    out_eq = os.path.join(OUT_DIR, "strategy2_equity_curve.csv")
    equity_df.to_csv(out_eq, index=False)

    s2_sum = summarize_trades(trades_df, "STRATEGY 2 (3EMA+ATR)", INITIAL_CAPITAL)
    out_json = os.path.join(OUT_DIR, "strategy2_summary.json")
    with open(out_json, "w") as f:
        json.dump(s2_sum, f, indent=2, default=str)

    return trades_df, equity_df, s2_sum


def main():
    df_1m = load_and_prep_data(CSV_FILE_PATH)
    if df_1m.empty:
        raise SystemExit("[BT-REF] No data after date filter.")

    trades_s1 = pd.DataFrame()
    trades_s2 = pd.DataFrame()
    s1_sum = summarize_trades(pd.DataFrame(), "STRATEGY 1 (BB)", INITIAL_CAPITAL)
    s2_sum = summarize_trades(pd.DataFrame(), "STRATEGY 2 (3EMA+ATR)", INITIAL_CAPITAL)

    if ENABLE_STRATEGY_1:
        print("[BT-REF] Preparing Strategy1 (BB) aligned signals ...")
        df_s1 = prep_strategy1_signals(df_1m)
        if df_s1.empty:
            print("[BT-REF] Strategy1: insufficient data.")
        else:
            print("[BT-REF] Running Strategy1 (BB) ...")
            trades_s1, s1_sum = run_bt_ref_strategy1(df_s1)
            print_summary("STRATEGY 1 (BB)", s1_sum)

    if ENABLE_STRATEGY_2:
        print("[BT-REF] Preparing Strategy2 (3EMA + ATR) aligned signals ...")
        df_s2 = prep_strategy2_signals(df_1m)
        if df_s2.empty:
            print("[BT-REF] Strategy2: insufficient data.")
        else:
            print("[BT-REF] Running Strategy2 (3EMA + ATR) ...")
            trades_s2, equity_s2, s2_sum = run_bt_ref_strategy2(df_s2)
            print_summary("STRATEGY 2 (3EMA + ATR)", s2_sum)

    combo = combined_summary(s1_sum, s2_sum)
    combo_json = os.path.join(OUT_DIR, "combined_summary.json")
    with open(combo_json, "w") as f:
        json.dump(combo, f, indent=2, default=str)

    print_summary("COMBINED (S1 + S2)", {
        "initial_capital": combo["initial_capital"],
        "final_equity": combo["combined_final_equity"],
        "net_pnl": combo["combined_net_pnl"],
        "num_trades": combo["combined_trades"],
        "commission_rate": combo["commission_rate"],
        "start_date": combo["start_date"],
        "end_date": combo["end_date"],
    })

    print("\n[BT-REF] Outputs written to:")
    print(f"  {OUT_DIR}/strategy1_trades_log.csv")
    print(f"  {OUT_DIR}/strategy2_trades_log.csv")
    print(f"  {OUT_DIR}/strategy1_summary.json")
    print(f"  {OUT_DIR}/strategy2_summary.json")
    print(f"  {OUT_DIR}/combined_summary.json")


if __name__ == "__main__":
    main()
