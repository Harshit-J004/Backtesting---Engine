import pandas as pd
import numpy as np
from datetime import datetime

# ==========================================
# STRATEGY ENABLE FLAGS
# ==========================================
ENABLE_STRATEGY_1 = True   # Bollinger Bands strategy (from test1.py)
ENABLE_STRATEGY_2 = True   # 3EMA + ATR strategy (from test2.py)

# ==========================================
# COMMON CONFIGURATION
# ==========================================
CSV_FILE_PATH = "/mnt/c/Users/spkri/OneDrive/Desktop/Python/reliance_1m.csv"
START_DATE = '2023-01-01'
END_DATE = '2024-12-31'

INITIAL_CAPITAL = 10000.0
COMMISSION_RATE = 0.0002  # 0.02% per trade

# ==========================================
# STRATEGY 1 CONFIGURATION (Bollinger Bands)
# ==========================================
S1_PCT_EQUITY = 0.5       # 1.0 = 100% of equity per trade
S1_LENGTH = 20
S1_MULT = 2.5
S1_DIRECTION = 0          # 0 = Both, 1 = Long Only, -1 = Short Only

# ==========================================
# STRATEGY 2 CONFIGURATION (3EMA + ATR)
# ==========================================
S2_PCT_EQUITY = 0.1       # 1.0 = 100% of equity per trade
S2_SLOW_EMA_LEN = 30
S2_MID_EMA_LEN = 12
S2_FAST_EMA_LEN = 7
S2_ATR_LEN = 7
S2_TP_ATR_MULT = 4
S2_SL_ATR_MULT = 1


# ==========================================
# DATA LOADING AND PREPARATION
# ==========================================
def load_and_prep_data(filepath):
    print(f"Loading data from {filepath}...")
    try:
        df = pd.read_csv(filepath)
        df.columns = df.columns.str.strip().str.lower()

        # Handle Timestamp
        if 'timestamp' in df.columns:
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
        elif 'date' in df.columns:
            df['datetime'] = pd.to_datetime(df['date'])
        elif 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
        else:
            raise ValueError("Could not find 'timestamp', 'date', or 'datetime' column")

        df.set_index('datetime', inplace=True)
        df.sort_index(inplace=True)

        required_cols = ['open', 'high', 'low', 'close']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        print(f"Data loaded successfully: {len(df)} rows from {df.index[0]} to {df.index[-1]}")
        return df

    except Exception as e:
        print(f"CRITICAL ERROR loading data: {e}")
        print("Generating dummy data so you can see the code run...")
        dates = pd.date_range(start='2023-01-01', periods=10000, freq='1min')
        price_curve = 100 * np.cumprod(1 + np.random.normal(0, 0.001, len(dates)))
        data = {
            'open': price_curve,
            'high': price_curve * 1.002,
            'low': price_curve * 0.998,
            'close': price_curve + np.random.normal(0, 0.1, len(dates))
        }
        return pd.DataFrame(data, index=dates)


def calculate_rma(series, length):
    """
    Calculates Wilder's Moving Average (RMA), used by Pine Script for ATR.
    RMA is equivalent to EMA with alpha = 1/length.
    """
    return series.ewm(alpha=1/length, adjust=False).mean()


# ==========================================
# STRATEGY 1: BOLLINGER BANDS
# ==========================================
def resample_indicators_strategy1(df_1m):
    print("Strategy 1: Resampling data to 45min and calculating Bollinger Bands indicators...")

    # 1. Resample to 45min (Aggregating 1m bars)
    df_45m = df_1m.resample('45min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna()

    if len(df_45m) < S1_LENGTH:
        print("Not enough data to calculate indicators.")
        return pd.DataFrame()

    # 2. Calculate Indicators on 45m Close
    df_45m['sma'] = df_45m['close'].rolling(window=S1_LENGTH).mean()
    df_45m['std'] = df_45m['close'].rolling(window=S1_LENGTH).std()
    df_45m['upper'] = df_45m['sma'] + (S1_MULT * df_45m['std'])
    df_45m['lower'] = df_45m['sma'] - (S1_MULT * df_45m['std'])

    # 3. Calculate Raw Signals
    df_45m['prev_close'] = df_45m['close'].shift(1)
    df_45m['prev_lower'] = df_45m['lower'].shift(1)
    df_45m['prev_upper'] = df_45m['upper'].shift(1)

    df_45m['long_signal'] = (df_45m['prev_close'] < df_45m['prev_lower']) & (df_45m['close'] > df_45m['lower'])
    df_45m['short_signal'] = (df_45m['prev_close'] > df_45m['prev_upper']) & (df_45m['close'] < df_45m['upper'])

    # 4. Anti-Lookahead Shift
    df_45m['active_long_signal'] = df_45m['long_signal'].shift(1)
    df_45m['active_short_signal'] = df_45m['short_signal'].shift(1)
    df_45m['entry_stop_lower'] = df_45m['lower'].shift(1)
    df_45m['entry_stop_upper'] = df_45m['upper'].shift(1)

    return df_45m


def run_backtest_strategy1(df_1m, df_45m):
    print("Strategy 1: Running backtest execution loop...")

    # Align 45m data to 1m data
    cols_to_merge = ['active_long_signal', 'active_short_signal', 'entry_stop_lower', 'entry_stop_upper']
    aligned_signals = df_45m[cols_to_merge].reindex(df_1m.index, method='ffill')
    df = df_1m.join(aligned_signals)

    mask = (df.index >= START_DATE) & (df.index <= END_DATE)
    df = df.loc[mask]

    if df.empty:
        print("Dataframe empty after date filtering.")
        return pd.DataFrame()

    position = 0      # 0: Flat, 1: Long, -1: Short
    entry_price = 0.0
    entry_time = None
    current_qty = 0.0
    equity = INITIAL_CAPITAL
    trades = []

    bankrupt = False  # NEW: stop trading if equity <= 0

    for time, row in df.iterrows():
        if bankrupt:
            break

        if equity <= 0:
            equity = 0.0
            bankrupt = True
            break

        if pd.isna(row['entry_stop_lower']):
            continue

        allow_long = (S1_DIRECTION == 0) or (S1_DIRECTION == 1)
        allow_short = (S1_DIRECTION == 0) or (S1_DIRECTION == -1)

        # -----------------------------
        # LONG ENTRY
        # -----------------------------
        if row['active_long_signal'] == True and allow_long and equity > 0:
            stop_price = row['entry_stop_lower']
            fill_price = None

            if row['open'] >= stop_price:
                fill_price = row['open']
            elif row['high'] >= stop_price:
                fill_price = stop_price

            if fill_price is not None:
                # Close Short (if exists)
                if position == -1:
                    gross_pnl = (entry_price - fill_price) * current_qty
                    entry_comm = entry_price * current_qty * COMMISSION_RATE
                    exit_comm = fill_price * current_qty * COMMISSION_RATE
                    total_comm = entry_comm + exit_comm
                    net_pnl = gross_pnl - total_comm
                    equity += net_pnl

                    # Clamp + stop if bankrupt
                    if equity <= 0:
                        equity = 0.0
                        bankrupt = True

                    trades.append({
                        'type': 'Short',
                        'entry_time': entry_time,
                        'exit_time': time,
                        'entry_price': entry_price,
                        'exit_price': fill_price,
                        'qty': current_qty,
                        'gross_pnl': gross_pnl,
                        'commission': total_comm,
                        'net_pnl': net_pnl,
                        'equity': equity
                    })
                    position = 0
                    current_qty = 0.0

                    if bankrupt:
                        break

                # Open Long (if flat)
                if position == 0 and equity > 0:
                    position = 1
                    entry_price = fill_price
                    entry_time = time
                    allocatable_equity = equity * S1_PCT_EQUITY
                    current_qty = allocatable_equity / fill_price

        # -----------------------------
        # SHORT ENTRY
        # -----------------------------
        elif row['active_short_signal'] == True and allow_short and equity > 0:
            stop_price = row['entry_stop_upper']
            fill_price = None

            if row['open'] <= stop_price:
                fill_price = row['open']
            elif row['low'] <= stop_price:
                fill_price = stop_price

            if fill_price is not None:
                # Close Long (if exists)
                if position == 1:
                    gross_pnl = (fill_price - entry_price) * current_qty
                    entry_comm = entry_price * current_qty * COMMISSION_RATE
                    exit_comm = fill_price * current_qty * COMMISSION_RATE
                    total_comm = entry_comm + exit_comm
                    net_pnl = gross_pnl - total_comm
                    equity += net_pnl

                    # Clamp + stop if bankrupt
                    if equity <= 0:
                        equity = 0.0
                        bankrupt = True

                    trades.append({
                        'type': 'Long',
                        'entry_time': entry_time,
                        'exit_time': time,
                        'entry_price': entry_price,
                        'exit_price': fill_price,
                        'qty': current_qty,
                        'gross_pnl': gross_pnl,
                        'commission': total_comm,
                        'net_pnl': net_pnl,
                        'equity': equity
                    })
                    position = 0
                    current_qty = 0.0

                    if bankrupt:
                        break

                # Open Short (if flat)
                if position == 0 and equity > 0:
                    position = -1
                    entry_price = fill_price
                    entry_time = time
                    allocatable_equity = equity * S1_PCT_EQUITY
                    current_qty = allocatable_equity / fill_price

    # Close Open Positions at End of Backtest (only if not bankrupt and still have equity logic)
    if (not bankrupt) and position != 0:
        last_price = df.iloc[-1]['close']
        if position == 1:
            gross_pnl = (last_price - entry_price) * current_qty
            entry_comm = entry_price * current_qty * COMMISSION_RATE
            exit_comm = last_price * current_qty * COMMISSION_RATE
            total_comm = entry_comm + exit_comm
            net_pnl = gross_pnl - total_comm
            equity += net_pnl
            if equity <= 0:
                equity = 0.0

            trades.append({
                'type': 'Long (End)',
                'entry_time': entry_time,
                'exit_time': df.index[-1],
                'entry_price': entry_price,
                'exit_price': last_price,
                'qty': current_qty,
                'gross_pnl': gross_pnl,
                'commission': total_comm,
                'net_pnl': net_pnl,
                'equity': equity
            })
        elif position == -1:
            gross_pnl = (entry_price - last_price) * current_qty
            entry_comm = entry_price * current_qty * COMMISSION_RATE
            exit_comm = last_price * current_qty * COMMISSION_RATE
            total_comm = entry_comm + exit_comm
            net_pnl = gross_pnl - total_comm
            equity += net_pnl
            if equity <= 0:
                equity = 0.0

            trades.append({
                'type': 'Short (End)',
                'entry_time': entry_time,
                'exit_time': df.index[-1],
                'entry_price': entry_price,
                'exit_price': last_price,
                'qty': current_qty,
                'gross_pnl': gross_pnl,
                'commission': total_comm,
                'net_pnl': net_pnl,
                'equity': equity
            })

    return pd.DataFrame(trades)


# ==========================================
# STRATEGY 2: 3EMA + ATR
# ==========================================
def resample_indicators_strategy2(df_1m):
    print("Strategy 2: Resampling data to 45min and calculating 3EMA + ATR...")

    # 1. Resample to 45min
    df_45m = df_1m.resample('45min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna()

    if len(df_45m) < S2_SLOW_EMA_LEN:
        print("Not enough data to calculate indicators.")
        return pd.DataFrame()

    # 2. Calculate EMAs
    df_45m['ema_fast'] = df_45m['close'].ewm(span=S2_FAST_EMA_LEN, adjust=False).mean()
    df_45m['ema_mid'] = df_45m['close'].ewm(span=S2_MID_EMA_LEN, adjust=False).mean()
    df_45m['ema_slow'] = df_45m['close'].ewm(span=S2_SLOW_EMA_LEN, adjust=False).mean()

    # 3. Calculate ATR
    df_45m['prev_close'] = df_45m['close'].shift(1)
    df_45m['tr1'] = df_45m['high'] - df_45m['low']
    df_45m['tr2'] = abs(df_45m['high'] - df_45m['prev_close'])
    df_45m['tr3'] = abs(df_45m['low'] - df_45m['prev_close'])
    df_45m['tr'] = df_45m[['tr1', 'tr2', 'tr3']].max(axis=1)
    df_45m['atr'] = calculate_rma(df_45m['tr'], S2_ATR_LEN)

    # 4. Generate Signals
    df_45m['prev_ema_mid'] = df_45m['ema_mid'].shift(1)
    df_45m['prev_ema_slow'] = df_45m['ema_slow'].shift(1)
    df_45m['prev_ema_fast'] = df_45m['ema_fast'].shift(1)

    # Entry: Crossover(Mid, Slow)
    df_45m['long_entry_signal'] = (df_45m['prev_ema_mid'] <= df_45m['prev_ema_slow']) & \
                                  (df_45m['ema_mid'] > df_45m['ema_slow'])

    # Exit: Crossunder(Fast, Mid)
    df_45m['exit_signal'] = (df_45m['prev_ema_fast'] >= df_45m['prev_ema_mid']) & \
                            (df_45m['ema_fast'] < df_45m['ema_mid'])

    # 5. Anti-Lookahead & Signal ID Generation
    df_45m['signal_id'] = df_45m.index

    # Shift forward by 1 to simulate execution on NEXT bar
    df_45m['active_entry_signal'] = df_45m['long_entry_signal'].shift(1)
    df_45m['active_exit_signal'] = df_45m['exit_signal'].shift(1)
    df_45m['active_signal_id'] = df_45m['signal_id'].shift(1)

    df_45m['signal_bar_close'] = df_45m['close'].shift(1)
    df_45m['signal_bar_atr'] = df_45m['atr'].shift(1)

    return df_45m


def run_backtest_strategy2(df_1m, df_45m):
    print("Strategy 2: Running backtest execution loop...")

    cols_to_merge = ['active_entry_signal', 'active_exit_signal', 'signal_bar_close', 'signal_bar_atr', 'active_signal_id']
    aligned_signals = df_45m[cols_to_merge].reindex(df_1m.index, method='ffill')
    df = df_1m.join(aligned_signals)

    mask = (df.index >= START_DATE) & (df.index <= END_DATE)
    df = df.loc[mask]

    if df.empty:
        print("Dataframe empty after date filtering.")
        return pd.DataFrame(), pd.DataFrame()

    position = 0      # 0: Flat, 1: Long
    entry_price = 0.0
    entry_time = None

    take_profit_price = 0.0
    stop_loss_price = 0.0

    current_qty = 0.0
    equity = INITIAL_CAPITAL

    last_traded_signal_id = None

    trades = []
    equity_curve = []

    bankrupt = False  # NEW

    for time, row in df.iterrows():
        current_close = row['close']
        current_high = row['high']
        current_low = row['low']
        current_open = row['open']

        # --- Floating Equity Calculation ---
        floating_equity = equity
        if position == 1:
            unrealized_pnl = (current_close - entry_price) * current_qty
            floating_equity = equity + unrealized_pnl

        # Clamp floating equity for reporting
        equity_curve.append({'time': time, 'equity': max(floating_equity, 0.0)})

        if bankrupt:
            continue

        # NEW: margin call / bankruptcy check using floating equity
        if position == 1 and floating_equity <= 0:
            # Force exit immediately at current_close (simple & deterministic)
            exit_reason = 'Margin Call'
            exit_price = current_close

            gross_pnl = (exit_price - entry_price) * current_qty
            entry_comm = entry_price * current_qty * COMMISSION_RATE
            exit_comm = exit_price * current_qty * COMMISSION_RATE
            total_comm = entry_comm + exit_comm
            net_pnl = gross_pnl - total_comm
            equity += net_pnl

            if equity <= 0:
                equity = 0.0
                bankrupt = True

            trades.append({
                'type': 'Long',
                'reason': exit_reason,
                'entry_time': entry_time,
                'exit_time': time,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'qty': current_qty,
                'gross_pnl': gross_pnl,
                'commission': total_comm,
                'net_pnl': net_pnl,
                'equity': equity
            })

            position = 0
            current_qty = 0.0
            entry_price = 0.0
            entry_time = None
            continue

        # NEW: stop trading if realized equity is gone
        if equity <= 0:
            equity = 0.0
            bankrupt = True
            continue

        if pd.isna(row['signal_bar_atr']):
            continue

        # ==========================================
        # 1. EXIT LOGIC
        # ==========================================
        if position == 1:
            exit_reason = None
            exit_price = None

            # A. Check TP/SL
            if current_low <= stop_loss_price:
                exit_reason = 'Stop Loss'
                exit_price = stop_loss_price
                if row['open'] < stop_loss_price:
                    exit_price = row['open']

            elif current_high >= take_profit_price:
                exit_reason = 'Take Profit'
                exit_price = take_profit_price
                if row['open'] > take_profit_price:
                    exit_price = row['open']

            # B. Check Early Exit Signal (Trend Reversal)
            elif row['active_exit_signal'] == True:
                exit_reason = 'EMA Cross Exit'
                exit_price = row['open']

            # --- Execute Exit ---
            if exit_price is not None:
                gross_pnl = (exit_price - entry_price) * current_qty
                entry_comm = entry_price * current_qty * COMMISSION_RATE
                exit_comm = exit_price * current_qty * COMMISSION_RATE
                total_comm = entry_comm + exit_comm
                net_pnl = gross_pnl - total_comm
                equity += net_pnl

                if equity <= 0:
                    equity = 0.0
                    bankrupt = True

                trades.append({
                    'type': 'Long',
                    'reason': exit_reason,
                    'entry_time': entry_time,
                    'exit_time': time,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'qty': current_qty,
                    'gross_pnl': gross_pnl,
                    'commission': total_comm,
                    'net_pnl': net_pnl,
                    'equity': equity
                })

                position = 0
                current_qty = 0.0
                entry_price = 0.0
                entry_time = None

        # ==========================================
        # 2. ENTRY LOGIC
        # ==========================================
        if (not bankrupt) and position == 0 and equity > 0:
            if row['active_entry_signal'] == True:
                current_signal_id = row['active_signal_id']

                if current_signal_id != last_traded_signal_id:
                    position = 1
                    entry_price = row['open']
                    entry_time = time
                    last_traded_signal_id = current_signal_id

                    allocatable_equity = equity * S2_PCT_EQUITY
                    current_qty = allocatable_equity / entry_price

                    atr_val = row['signal_bar_atr']
                    ref_close = row['signal_bar_close']
                    take_profit_price = ref_close + (atr_val * S2_TP_ATR_MULT)
                    stop_loss_price = ref_close - (atr_val * S2_SL_ATR_MULT)

    # Close at End (only if not bankrupt and still in position)
    if (not bankrupt) and position == 1:
        last_price = df.iloc[-1]['close']
        gross_pnl = (last_price - entry_price) * current_qty
        entry_comm = entry_price * current_qty * COMMISSION_RATE
        exit_comm = last_price * current_qty * COMMISSION_RATE
        total_comm = entry_comm + exit_comm
        net_pnl = gross_pnl - total_comm
        equity += net_pnl
        if equity <= 0:
            equity = 0.0

        trades.append({
            'type': 'Long (End)',
            'reason': 'Backtest End',
            'entry_time': entry_time,
            'exit_time': df.index[-1],
            'entry_price': entry_price,
            'exit_price': last_price,
            'qty': current_qty,
            'gross_pnl': gross_pnl,
            'commission': total_comm,
            'net_pnl': net_pnl,
            'equity': equity
        })

    return pd.DataFrame(trades), pd.DataFrame(equity_curve)


# ==========================================
# METRICS
# ==========================================
def calculate_metrics_strategy1(trades_df):
    if trades_df.empty:
        print("\nStrategy 1: No trades generated.")
        return

    wins = trades_df[trades_df['net_pnl'] > 0]
    win_rate = (len(wins) / len(trades_df)) * 100 if len(trades_df) > 0 else 0
    total_pnl = trades_df.iloc[-1]['equity'] - INITIAL_CAPITAL
    total_commission = trades_df['commission'].sum()

    trades_df['peak'] = trades_df['equity'].cummax()
    trades_df['drawdown'] = (trades_df['equity'] - trades_df['peak']) / trades_df['peak']
    # FIX: report as positive magnitude
    max_dd = abs(trades_df['drawdown'].min()) * 100

    print("\n" + "="*40)
    print(" STRATEGY 1: BOLLINGER BANDS")
    print("="*40)
    print(f"Total Trades:     {len(trades_df)}")
    print(f"Win Rate:         {win_rate:.2f}%")
    print(f"Total Gross PnL:  ${(total_pnl + total_commission):.2f}")
    print(f"Total Commission: ${total_commission:.2f}")
    print(f"Total Net PnL:    ${total_pnl:.2f}")
    print(f"Final Equity:     ${trades_df.iloc[-1]['equity']:.2f}")
    print(f"Max Drawdown:     {max_dd:.2f}%")
    print("="*40)

    print("\nTrade Log (First 20):")
    log_cols = ['entry_time', 'exit_time', 'type', 'entry_price', 'exit_price', 'commission', 'net_pnl', 'equity']
    print(trades_df[log_cols].head(20).to_string())

    try:
        filename = 'strategy1_trades_log.csv'
        trades_df.to_csv(filename)
        print(f"\n[SUCCESS] Strategy 1 trade log exported to '{filename}'")
    except Exception as e:
        print(f"\n[ERROR] Could not export CSV: {e}")


def calculate_metrics_strategy2(trades_df, equity_df):
    if trades_df.empty:
        print("\nStrategy 2: No trades generated.")
        return

    wins = trades_df[trades_df['net_pnl'] > 0]
    win_rate = (len(wins) / len(trades_df)) * 100 if len(trades_df) > 0 else 0
    total_pnl = trades_df.iloc[-1]['equity'] - INITIAL_CAPITAL
    total_commission = trades_df['commission'].sum()

    equity_df.set_index('time', inplace=True)
    equity_df['peak'] = equity_df['equity'].cummax()
    equity_df['drawdown'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak']
    # FIX: report as positive magnitude
    max_dd = abs(equity_df['drawdown'].min()) * 100

    print("\n" + "="*40)
    print(" STRATEGY 2: 3EMA + ATR")
    print("="*40)
    print(f"Total Trades:     {len(trades_df)}")
    print(f"Win Rate:         {win_rate:.2f}%")
    print(f"Total Gross PnL:  ${(total_pnl + total_commission):.2f}")
    print(f"Total Commission: ${total_commission:.2f}")
    print(f"Total Net PnL:    ${total_pnl:.2f}")
    print(f"Final Equity:     ${trades_df.iloc[-1]['equity']:.2f}")
    print(f"Max Drawdown:     {max_dd:.2f}% (Floating)")
    print("="*40)

    print("\nTrade Log (First 20):")
    log_cols = ['entry_time', 'reason', 'entry_price', 'exit_price', 'net_pnl', 'equity']
    print(trades_df[log_cols].head(20).to_string())

    try:
        filename = 'strategy2_trades_log.csv'
        trades_df.to_csv(filename)
        print(f"\n[SUCCESS] Strategy 2 trade log exported to '{filename}'")
    except Exception as e:
        print(f"\n[ERROR] Could not export CSV: {e}")


def calculate_combined_metrics(trades_s1, trades_s2):
    """Calculate and display combined results from both strategies."""

    print("\n" + "="*50)
    print(" COMBINED RESULTS (STRATEGY 1 + STRATEGY 2)")
    print("="*50)

    total_trades = 0
    total_wins = 0
    total_gross_pnl = 0.0
    total_commission = 0.0
    total_net_pnl = 0.0
    combined_final_equity = INITIAL_CAPITAL

    s1_net_pnl = 0.0
    s1_trades = 0
    s1_wins = 0
    if not trades_s1.empty:
        s1_trades = len(trades_s1)
        s1_wins = len(trades_s1[trades_s1['net_pnl'] > 0])
        s1_net_pnl = trades_s1.iloc[-1]['equity'] - INITIAL_CAPITAL
        s1_commission = trades_s1['commission'].sum()

        total_trades += s1_trades
        total_wins += s1_wins
        total_gross_pnl += (s1_net_pnl + s1_commission)
        total_commission += s1_commission
        total_net_pnl += s1_net_pnl

    s2_net_pnl = 0.0
    s2_trades = 0
    s2_wins = 0
    if not trades_s2.empty:
        s2_trades = len(trades_s2)
        s2_wins = len(trades_s2[trades_s2['net_pnl'] > 0])
        s2_net_pnl = trades_s2.iloc[-1]['equity'] - INITIAL_CAPITAL
        s2_commission = trades_s2['commission'].sum()

        total_trades += s2_trades
        total_wins += s2_wins
        total_gross_pnl += (s2_net_pnl + s2_commission)
        total_commission += s2_commission
        total_net_pnl += s2_net_pnl

    combined_final_equity = INITIAL_CAPITAL + total_net_pnl

    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    roi = (total_net_pnl / INITIAL_CAPITAL * 100) if INITIAL_CAPITAL > 0 else 0

    all_trades = []

    if not trades_s1.empty:
        for _, row in trades_s1.iterrows():
            all_trades.append({
                'time': row['exit_time'],
                'pnl': row['net_pnl'],
                'strategy': 'S1'
            })

    if not trades_s2.empty:
        for _, row in trades_s2.iterrows():
            all_trades.append({
                'time': row['exit_time'],
                'pnl': row['net_pnl'],
                'strategy': 'S2'
            })

    combined_max_dd = 0.0
    if all_trades:
        all_trades_df = pd.DataFrame(all_trades).sort_values('time')
        all_trades_df['cumulative_pnl'] = all_trades_df['pnl'].cumsum()
        all_trades_df['equity'] = INITIAL_CAPITAL + all_trades_df['cumulative_pnl']

        all_trades_df['peak'] = all_trades_df['equity'].cummax()
        all_trades_df['drawdown'] = (all_trades_df['equity'] - all_trades_df['peak']) / all_trades_df['peak']
        # FIX: report as positive magnitude
        combined_max_dd = abs(all_trades_df['drawdown'].min()) * 100

    print(f"\nInitial Capital:     ${INITIAL_CAPITAL:.2f}")
    print(f"\n--- Strategy Breakdown ---")
    print(f"Strategy 1 (BB):     {s1_trades} trades, ${s1_net_pnl:.2f} PnL")
    print(f"Strategy 2 (3EMA):   {s2_trades} trades, ${s2_net_pnl:.2f} PnL")
    print(f"\n--- Combined Totals ---")
    print(f"Total Trades:        {total_trades}")
    print(f"Total Wins:          {total_wins}")
    print(f"Combined Win Rate:   {win_rate:.2f}%")
    print(f"Total Gross PnL:     ${total_gross_pnl:.2f}")
    print(f"Total Commission:    ${total_commission:.2f}")
    print(f"Total Net PnL:       ${total_net_pnl:.2f}")
    print(f"Combined Equity:     ${combined_final_equity:.2f}")
    print(f"Combined Max DD:     {combined_max_dd:.2f}%")
    print(f"ROI:                 {roi:.2f}%")
    print("="*50)


# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    df_1m = load_and_prep_data(CSV_FILE_PATH)

    if df_1m.empty:
        print("Failed to load data. Exiting.")
        exit(1)

    trades_s1 = pd.DataFrame()
    trades_s2 = pd.DataFrame()

    if ENABLE_STRATEGY_1:
        print("\n" + "="*50)
        print(" RUNNING STRATEGY 1: BOLLINGER BANDS")
        print("="*50)
        df_45m_s1 = resample_indicators_strategy1(df_1m)

        if not df_45m_s1.empty:
            trades_s1 = run_backtest_strategy1(df_1m, df_45m_s1)
            calculate_metrics_strategy1(trades_s1)
        else:
            print("Strategy 1: Could not calculate indicators.")
    else:
        print("\nStrategy 1 (Bollinger Bands) is DISABLED.")

    if ENABLE_STRATEGY_2:
        print("\n" + "="*50)
        print(" RUNNING STRATEGY 2: 3EMA + ATR")
        print("="*50)
        df_45m_s2 = resample_indicators_strategy2(df_1m)

        if not df_45m_s2.empty:
            trades_s2, equity_curve_s2 = run_backtest_strategy2(df_1m, df_45m_s2)
            calculate_metrics_strategy2(trades_s2, equity_curve_s2)
        else:
            print("Strategy 2: Could not calculate indicators.")
    else:
        print("\nStrategy 2 (3EMA + ATR) is DISABLED.")

    if ENABLE_STRATEGY_1 and ENABLE_STRATEGY_2:
        calculate_combined_metrics(trades_s1, trades_s2)

    print("\n" + "="*50)
    print(" BACKTEST COMPLETE")
    print("="*50)
