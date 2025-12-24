import numpy as np
from typing import List, Tuple
import json
import csv
from datetime import datetime


def compute_returns(equity_curve: List[float]) -> np.ndarray:
    eq = np.array(equity_curve)
    returns = np.diff(eq) / eq[:-1]
    return returns


def sharpe_ratio(returns: np.ndarray, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    if len(returns) < 2 or np.std(returns) == 0:
        return 0.0
    excess_returns = returns - risk_free_rate / periods_per_year
    return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(periods_per_year)


def sortino_ratio(returns: np.ndarray, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    excess_returns = returns - risk_free_rate / periods_per_year
    downside = returns[returns < 0]
    if len(downside) == 0 or np.std(downside) == 0:
        return np.inf if np.mean(excess_returns) > 0 else 0.0
    return np.mean(excess_returns) / np.std(downside) * np.sqrt(periods_per_year)


def max_drawdown(equity_curve: List[float]) -> Tuple[float, int, int]:
    eq = np.array(equity_curve)
    peak = eq[0]
    peak_idx = 0
    max_dd = 0.0
    max_dd_peak_idx = 0
    max_dd_trough_idx = 0
    
    for i, val in enumerate(eq):
        if val > peak:
            peak = val
            peak_idx = i
        dd = (peak - val) / peak
        if dd > max_dd:
            max_dd = dd
            max_dd_peak_idx = peak_idx
            max_dd_trough_idx = i
    
    return max_dd, max_dd_peak_idx, max_dd_trough_idx


def cagr(equity_curve: List[float], periods_per_year: int = 252) -> float:
    if len(equity_curve) < 2 or equity_curve[0] <= 0:
        return 0.0
    years = len(equity_curve) / periods_per_year
    if years == 0:
        return 0.0
    return (equity_curve[-1] / equity_curve[0]) ** (1 / years) - 1


def win_rate(trades: List[dict]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
    return wins / len(trades)


def average_win_loss(trades: List[dict]) -> Tuple[float, float]:
    wins = [t['pnl'] for t in trades if t.get('pnl', 0) > 0]
    losses = [t['pnl'] for t in trades if t.get('pnl', 0) < 0]
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    return avg_win, avg_loss



class BacktestResults:
    def __init__(self, equity_curve: List[float], trades: List[dict], 
                 initial_capital: float = 100000.0,
                 start_date: datetime = None, end_date: datetime = None):
        self.equity_curve = equity_curve
        self.trades = trades
        self.initial_capital = initial_capital
        self.starts_at = start_date
        self.ends_at = end_date
        self.returns = compute_returns(equity_curve) if len(equity_curve) > 1 else np.array([])
        
    def summary(self) -> dict:
        max_dd, peak_idx, trough_idx = max_drawdown(self.equity_curve)
        avg_win, avg_loss = average_win_loss(self.trades)
        
        # Calculate duration in years for correct annualization
        years = 0.0
        periods_per_year = 252 # Fallback
        
        if self.starts_at and self.ends_at:
            duration = (self.ends_at - self.starts_at).total_seconds()
            if duration > 0:
                years = duration / (365.25 * 24 * 3600)
                # Dynamic periods per year based on tick resolution
                if len(self.equity_curve) > 1:
                    total_ticks = len(self.equity_curve)
                    periods_per_year = total_ticks / years

        # Re-calc CAGR with time
        cagr_val = 0.0
        final_eq = self.equity_curve[-1] if self.equity_curve else self.initial_capital
        if years > 0 and self.initial_capital > 0 and final_eq > 0:
             cagr_val = (final_eq / self.initial_capital) ** (1 / years) - 1

        return {
            'initial_capital': self.initial_capital,
            'final_equity': self.equity_curve[-1] if self.equity_curve else self.initial_capital,
            'total_pnl': self.equity_curve[-1] - self.initial_capital if self.equity_curve else 0.0,
            'total_return_pct': (self.equity_curve[-1] / self.initial_capital - 1) * 100 if self.equity_curve else 0.0,
            'sharpe_ratio': sharpe_ratio(self.returns, periods_per_year=periods_per_year),
            'sortino_ratio': sortino_ratio(self.returns, periods_per_year=periods_per_year),
            'max_drawdown_pct': max_dd * 100,
            'cagr_pct': cagr_val * 100,
            'total_trades': len(self.trades),
            'win_rate_pct': win_rate(self.trades) * 100,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': abs(avg_win / avg_loss) if avg_loss != 0 else np.inf,
            'duration_days': (self.ends_at - self.starts_at).days if (self.starts_at and self.ends_at) else 0
        }
    
    def print_summary(self):
        """Print formatted summary."""
        s = self.summary()
        print("\n" + "=" * 50)
        print("BACKTEST RESULTS")
        print("=" * 50)
        print(f"Duration:           {s.get('duration_days', 0)} days")
        print(f"Initial Capital:    ${s['initial_capital']:,.2f}")
        print(f"Final Equity:       ${s['final_equity']:,.2f}")
        print(f"Total P&L:          ${s['total_pnl']:+,.2f} ({s['total_return_pct']:+.2f}%)")
        print("-" * 50)
        print(f"Sharpe Ratio:       {s['sharpe_ratio']:.2f}")
        print(f"Sortino Ratio:      {s['sortino_ratio']:.2f}")
        print(f"Max Drawdown:       {s['max_drawdown_pct']:.2f}%")
        print(f"CAGR:               {s['cagr_pct']:.2f}%")
        print("-" * 50)
        print(f"Total Trades:       {s['total_trades']}")
        print(f"Win Rate:           {s['win_rate_pct']:.1f}%")
        print(f"Avg Win:            ${s['avg_win']:,.2f}")
        print(f"Avg Loss:           ${s['avg_loss']:,.2f}")
        print(f"Profit Factor:      {s['profit_factor']:.2f}")
        print("=" * 50)
    
    def export_json(self, filepath: str):
        """Export results to JSON."""
        data = {
            'summary': self.summary(),
            'equity_curve': self.equity_curve,
            'trades': self.trades,
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        print(f"Results exported to {filepath}")
    
    def export_trades_csv(self, filepath: str):
        """Export trade log to CSV."""
        if not self.trades:
            print("No trades to export.")
            return
        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.trades[0].keys())
            writer.writeheader()
            writer.writerows(self.trades)
        print(f"Trade log exported to {filepath}")
