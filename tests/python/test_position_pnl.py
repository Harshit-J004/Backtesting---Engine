#!/usr/bin/env python3
# filepath: /home/joelb23/BacktestingEngine/tests/python/test_position_pnl.py
"""
Test Suite: Position Tracking & P&L Calculation
Validates:
- Position management (buy/sell/partial)
- Cash tracking
- Realized P&L calculation
- Unrealized P&L calculation
- Edge cases (limits, zero orders, insufficient cash)
"""

import os
import sys
import struct
import unittest
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "python"))

import felix_engine as fe
from felix.strategy.base import Strategy

TICK_FORMAT = '<QIfffffII'
TICK_SIZE = 40


def create_test_tick(timestamp_ns, symbol_id, price, volume=1000):
    """Create a tick record for testing"""
    bid = price
    ask = price
    return struct.pack(TICK_FORMAT, timestamp_ns, symbol_id, price, bid, ask, 100.0, 100.0, volume, 0)


def write_test_data(filepath, ticks):
    """Write test ticks to binary file"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'wb') as f:
        for tick in ticks:
            f.write(tick)


class TestStrategy(Strategy):
    """Strategy that executes predefined orders for testing"""
    
    def __init__(self, engine, portfolio, orders_to_execute):
        self.engine = engine
        self.portfolio = portfolio
        self.orders_to_execute = orders_to_execute  # List of (tick_num, side, size)
        self.tick_count = 0
        self.fills = []
        self.prices_seen = []
        self.equity_history = []
        
    def on_start(self):
        pass
    
    def on_tick(self, tick):
        self.tick_count += 1
        self.prices_seen.append(tick.price)
        self.equity_history.append(self.portfolio.equity())
        
        for order_tick, side, size in self.orders_to_execute:
            if order_tick == self.tick_count and size > 0:
                order = fe.Order()
                order.symbol_id = tick.symbol_id
                order.side = fe.Side.BUY if side == 'BUY' else fe.Side.SELL
                order.order_type = fe.OrderType.MARKET
                order.size = size
                order.price = tick.price
                order.timestamp = tick.timestamp
                
                order_id = self.engine.submit_order(order)
    
    def on_fill(self, fill):
        side_str = "BUY" if fill.side == fe.Side.BUY else "SELL"
        self.fills.append({
            'side': side_str,
            'price': fill.price,
            'volume': fill.volume,
            'timestamp': fill.timestamp
        })
    
    def on_bar(self, bar):
        pass
    
    def on_end(self):
        pass


def create_engine_components(initial_capital=100000.0, max_position=10000, slippage_bps=0.0):
    """Create fresh engine components"""
    slippage = fe.SlippageConfig()
    slippage.fixed_bps = slippage_bps
    
    latency = fe.LatencyConfig()
    latency.strategy_latency_ns = 0
    latency.engine_latency_ns = 0
    
    engine = fe.MatchingEngine(slippage)
    engine.set_latency_config(latency)
    
    portfolio = fe.Portfolio(initial_capital)
    
    risk_limits = fe.RiskLimits()
    risk_limits.max_drawdown = 1.0
    risk_limits.max_position_size = max_position
    risk_limits.max_order_size = max_position
    risk_limits.max_notional = 10000000.0
    risk_limits.max_daily_loss = 10000000.0
    risk_engine = fe.RiskEngine(risk_limits)
    
    return engine, portfolio, risk_engine


def run_backtest(test_file, orders, initial_capital=100000.0, max_position=10000, slippage_bps=0.0):
    """Run a backtest with given orders"""
    stream = fe.DataStream()
    stream.load(test_file)
    
    engine, portfolio, risk_engine = create_engine_components(initial_capital, max_position, slippage_bps)
    strategy = TestStrategy(engine, portfolio, orders)
    
    event_loop = fe.EventLoop()
    event_loop.set_matching_engine(engine)
    event_loop.set_portfolio(portfolio)
    event_loop.set_risk_engine(risk_engine)
    
    event_loop.run(stream, strategy, engine, portfolio)
    
    return {
        'portfolio': portfolio,
        'strategy': strategy,
        'fills': strategy.fills,
        'final_equity': portfolio.equity(),
        'final_cash': portfolio.cash()
    }


class TestPositionTracking(unittest.TestCase):
    """Position tracking tests"""
    
    @classmethod
    def setUpClass(cls):
        cls.test_data_dir = os.path.join(project_root, "data", "test")
        os.makedirs(cls.test_data_dir, exist_ok=True)
        cls.test_file = os.path.join(cls.test_data_dir, "test_pos_pnl.bin")
        cls.initial_capital = 100000.0
    
    def test_01_single_buy(self):
        """Buy 100 shares @ $255 -> Position=100, Cash=$74,500"""
        print("\n" + "="*60)
        print("TEST: Single Buy")
        print("="*60)
        
        ticks = [create_test_tick(1000000000 * (i+1), 1, 255.0) for i in range(5)]
        write_test_data(self.test_file, ticks)
        
        result = run_backtest(self.test_file, [(2, 'BUY', 100)])
        
        expected_cash = self.initial_capital - (100 * 255.0)
        
        print(f"Expected: Cash=${expected_cash:,.2f}, 1 fill")
        print(f"Actual:   Cash=${result['final_cash']:,.2f}, {len(result['fills'])} fill(s)")
        
        self.assertEqual(len(result['fills']), 1)
        self.assertEqual(result['fills'][0]['volume'], 100)
        self.assertAlmostEqual(result['final_cash'], expected_cash, delta=10.0)
        
        print("✓ PASSED")
    
    def test_02_buy_sell_flat(self):
        """Buy 100, Sell 100 @ same price -> Position=0, Cash=Initial"""
        print("\n" + "="*60)
        print("TEST: Buy Then Sell (Flat Price)")
        print("="*60)
        
        ticks = [create_test_tick(1000000000 * (i+1), 1, 255.0) for i in range(10)]
        write_test_data(self.test_file, ticks)
        
        result = run_backtest(self.test_file, [(2, 'BUY', 100), (5, 'SELL', 100)])
        
        print(f"Expected: Cash=${self.initial_capital:,.2f}, 2 fills")
        print(f"Actual:   Cash=${result['final_cash']:,.2f}, {len(result['fills'])} fill(s)")
        
        self.assertEqual(len(result['fills']), 2)
        self.assertAlmostEqual(result['final_cash'], self.initial_capital, delta=10.0)
        
        print("✓ PASSED")
    
    def test_03_buy_sell_profit(self):
        """Buy 100 @ $250, Sell @ $260 -> Profit=$1,000"""
        print("\n" + "="*60)
        print("TEST: Buy Then Sell (Price Up = Profit)")
        print("="*60)
        
        ticks = []
        base_ts = 1000000000
        # Ticks 1-3 @ $250
        for i in range(3):
            ticks.append(create_test_tick(base_ts + i * 1000000000, 1, 250.0))
        # Ticks 4-6 @ $260
        for i in range(3, 6):
            ticks.append(create_test_tick(base_ts + i * 1000000000, 1, 260.0))
        
        write_test_data(self.test_file, ticks)
        
        result = run_backtest(self.test_file, [(2, 'BUY', 100), (5, 'SELL', 100)])
        
        # Buy 100 @ $250 = spend $25,000 -> Cash = $75,000
        # Sell 100 @ $260 = receive $26,000 -> Cash = $101,000
        expected_pnl = 100 * (260.0 - 250.0)  # $1,000
        expected_cash = self.initial_capital + expected_pnl
        
        print(f"Expected: P&L=${expected_pnl:,.2f}, Cash=${expected_cash:,.2f}")
        print(f"Actual:   Cash=${result['final_cash']:,.2f}, Equity=${result['final_equity']:,.2f}")
        
        self.assertEqual(len(result['fills']), 2)
        self.assertAlmostEqual(result['final_cash'], expected_cash, delta=10.0)
        self.assertAlmostEqual(result['final_equity'], expected_cash, delta=10.0)
        
        print("✓ PASSED")
    
    def test_04_buy_sell_loss(self):
        """Buy 100 @ $260, Sell @ $250 -> Loss=$1,000"""
        print("\n" + "="*60)
        print("TEST: Buy Then Sell (Price Down = Loss)")
        print("="*60)
        
        ticks = []
        base_ts = 1000000000
        # Ticks 1-3 @ $260
        for i in range(3):
            ticks.append(create_test_tick(base_ts + i * 1000000000, 1, 260.0))
        # Ticks 4-6 @ $250
        for i in range(3, 6):
            ticks.append(create_test_tick(base_ts + i * 1000000000, 1, 250.0))
        
        write_test_data(self.test_file, ticks)
        
        result = run_backtest(self.test_file, [(2, 'BUY', 100), (5, 'SELL', 100)])
        
        expected_pnl = 100 * (250.0 - 260.0)  # -$1,000
        expected_cash = self.initial_capital + expected_pnl
        
        print(f"Expected: P&L=${expected_pnl:,.2f}, Cash=${expected_cash:,.2f}")
        print(f"Actual:   Cash=${result['final_cash']:,.2f}, Equity=${result['final_equity']:,.2f}")
        
        self.assertEqual(len(result['fills']), 2)
        self.assertAlmostEqual(result['final_cash'], expected_cash, delta=10.0)
        
        print("✓ PASSED")
    
    def test_05_partial_sell(self):
        """Buy 100, Sell 50 -> Position=50 remaining"""
        print("\n" + "="*60)
        print("TEST: Partial Sell")
        print("="*60)
        
        ticks = [create_test_tick(1000000000 * (i+1), 1, 255.0) for i in range(10)]
        write_test_data(self.test_file, ticks)
        
        result = run_backtest(self.test_file, [(2, 'BUY', 100), (5, 'SELL', 50)])
        
        # Buy 100 @ $255 = -$25,500
        # Sell 50 @ $255 = +$12,750
        # Cash = 100000 - 25500 + 12750 = $87,250
        # Position value = 50 * 255 = $12,750
        # Equity = $100,000
        expected_cash = self.initial_capital - (100 * 255.0) + (50 * 255.0)
        
        print(f"Expected: Cash=${expected_cash:,.2f}, Equity=${self.initial_capital:,.2f}")
        print(f"Actual:   Cash=${result['final_cash']:,.2f}, Equity=${result['final_equity']:,.2f}")
        
        self.assertEqual(len(result['fills']), 2)
        self.assertAlmostEqual(result['final_cash'], expected_cash, delta=10.0)
        self.assertAlmostEqual(result['final_equity'], self.initial_capital, delta=100.0)
        
        print("✓ PASSED")
    
    def test_06_multiple_buys_averaging(self):
        """Buy 50 @ $250, Buy 50 @ $260 -> Avg cost = $255"""
        print("\n" + "="*60)
        print("TEST: Multiple Buys (Cost Averaging)")
        print("="*60)
        
        ticks = []
        base_ts = 1000000000
        for i in range(3):
            ticks.append(create_test_tick(base_ts + i * 1000000000, 1, 250.0))
        for i in range(3, 6):
            ticks.append(create_test_tick(base_ts + i * 1000000000, 1, 260.0))
        for i in range(6, 9):
            ticks.append(create_test_tick(base_ts + i * 1000000000, 1, 255.0))
        
        write_test_data(self.test_file, ticks)
        
        result = run_backtest(self.test_file, [(2, 'BUY', 50), (4, 'BUY', 50)])
        
        # Cash spent: 50*250 + 50*260 = $25,500
        expected_cash = self.initial_capital - 25500
        # Position: 100 shares, valued at $255 = $25,500
        # Equity: $74,500 + $25,500 = $100,000
        
        print(f"Expected: Cash=${expected_cash:,.2f}, Equity=${self.initial_capital:,.2f}")
        print(f"Actual:   Cash=${result['final_cash']:,.2f}, Equity=${result['final_equity']:,.2f}")
        
        self.assertEqual(len(result['fills']), 2)
        self.assertAlmostEqual(result['final_cash'], expected_cash, delta=10.0)
        self.assertAlmostEqual(result['final_equity'], self.initial_capital, delta=100.0)
        
        print("✓ PASSED")
    
    def test_07_complex_sequence(self):
        """Buy 100, Sell 30, Buy 20, Sell 90 -> Position=0"""
        print("\n" + "="*60)
        print("TEST: Complex Position Sequence")
        print("="*60)
        
        ticks = [create_test_tick(1000000000 * (i+1), 1, 255.0) for i in range(15)]
        write_test_data(self.test_file, ticks)
        
        orders = [
            (2, 'BUY', 100),   # Pos: 100
            (4, 'SELL', 30),   # Pos: 70
            (6, 'BUY', 20),    # Pos: 90
            (8, 'SELL', 90),   # Pos: 0
        ]
        result = run_backtest(self.test_file, orders)
        
        # Net: +100 -30 +20 -90 = 0 shares
        # At same price, should return to initial
        
        print(f"Expected: Cash=${self.initial_capital:,.2f}, 4 fills")
        print(f"Actual:   Cash=${result['final_cash']:,.2f}, {len(result['fills'])} fill(s)")
        
        self.assertEqual(len(result['fills']), 4)
        self.assertAlmostEqual(result['final_cash'], self.initial_capital, delta=10.0)
        
        print("✓ PASSED")
    
    def test_08_unrealized_pnl(self):
        """Buy 100 @ $250, price moves to $260 (no sell) -> Unrealized P&L=$1,000"""
        print("\n" + "="*60)
        print("TEST: Unrealized P&L (No Sell)")
        print("="*60)
        
        ticks = []
        base_ts = 1000000000
        for i in range(3):
            ticks.append(create_test_tick(base_ts + i * 1000000000, 1, 250.0))
        for i in range(3, 6):
            ticks.append(create_test_tick(base_ts + i * 1000000000, 1, 260.0))
        
        write_test_data(self.test_file, ticks)
        
        result = run_backtest(self.test_file, [(2, 'BUY', 100)])  # Only buy, no sell
        
        # Cash: 100000 - 25000 = $75,000
        # Position: 100 @ $260 = $26,000
        # Equity: $75,000 + $26,000 = $101,000
        expected_cash = self.initial_capital - (100 * 250.0)
        expected_equity = expected_cash + (100 * 260.0)
        unrealized_pnl = expected_equity - self.initial_capital
        
        print(f"Expected: Cash=${expected_cash:,.2f}, Equity=${expected_equity:,.2f}, Unrealized P&L=${unrealized_pnl:,.2f}")
        print(f"Actual:   Cash=${result['final_cash']:,.2f}, Equity=${result['final_equity']:,.2f}")
        
        self.assertAlmostEqual(result['final_cash'], expected_cash, delta=10.0)
        self.assertAlmostEqual(result['final_equity'], expected_equity, delta=100.0)
        
        print("✓ PASSED")


class TestEdgeCases(unittest.TestCase):
    """Edge case tests"""
    
    @classmethod
    def setUpClass(cls):
        cls.test_data_dir = os.path.join(project_root, "data", "test")
        os.makedirs(cls.test_data_dir, exist_ok=True)
        cls.test_file = os.path.join(cls.test_data_dir, "test_edge.bin")
        cls.initial_capital = 100000.0
    
    def test_09_max_position_limit(self):
        """Try to buy 100 when max_position=50 -> Capped or rejected"""
        print("\n" + "="*60)
        print("TEST: Max Position Limit")
        print("="*60)
        
        ticks = [create_test_tick(1000000000 * (i+1), 1, 100.0) for i in range(10)]
        write_test_data(self.test_file, ticks)
        
        result = run_backtest(self.test_file, [(2, 'BUY', 100)], max_position=50)
        
        print(f"Max Position: 50, Attempted: 100")
        print(f"Fills: {len(result['fills'])}")
        if result['fills']:
            print(f"Actual fill size: {result['fills'][0]['volume']}")
        
        # Either rejected OR capped at 50
        if len(result['fills']) > 0:
            self.assertLessEqual(result['fills'][0]['volume'], 50)
        
        print("✓ PASSED")
    
    def test_10_zero_size_order(self):
        """Order with size=0 -> No fill"""
        print("\n" + "="*60)
        print("TEST: Zero Size Order")
        print("="*60)
        
        ticks = [create_test_tick(1000000000 * (i+1), 1, 255.0) for i in range(5)]
        write_test_data(self.test_file, ticks)
        
        result = run_backtest(self.test_file, [(2, 'BUY', 0)])
        
        print(f"Expected: 0 fills")
        print(f"Actual:   {len(result['fills'])} fills")
        
        self.assertEqual(len(result['fills']), 0)
        self.assertAlmostEqual(result['final_equity'], self.initial_capital, delta=1.0)
        
        print("✓ PASSED")
    
    def test_11_slippage_effect(self):
        """Buy with 50bps slippage -> Worse fill price"""
        print("\n" + "="*60)
        print("TEST: Slippage Effect")
        print("="*60)
        
        ticks = [create_test_tick(1000000000 * (i+1), 1, 1000.0) for i in range(5)]
        write_test_data(self.test_file, ticks)
        
        # Without slippage
        result_no_slip = run_backtest(self.test_file, [(2, 'BUY', 100)], slippage_bps=0.0)
        
        # Reload stream
        ticks = [create_test_tick(1000000000 * (i+1), 1, 1000.0) for i in range(5)]
        write_test_data(self.test_file, ticks)
        
        # With 50bps slippage
        result_slip = run_backtest(self.test_file, [(2, 'BUY', 100)], slippage_bps=50.0)
        
        print(f"Without slippage: Fill @ ${result_no_slip['fills'][0]['price'] if result_no_slip['fills'] else 'N/A':.2f}")
        print(f"With 50bps slip:  Fill @ ${result_slip['fills'][0]['price'] if result_slip['fills'] else 'N/A':.2f}")
        
        if result_no_slip['fills'] and result_slip['fills']:
            # Slippage should make buy price higher
            self.assertGreaterEqual(result_slip['fills'][0]['price'], result_no_slip['fills'][0]['price'])
        
        print("✓ PASSED")
    
    def test_12_large_position_pnl(self):
        """Large position with price movement -> Large P&L"""
        print("\n" + "="*60)
        print("TEST: Large Position P&L")
        print("="*60)
        
        ticks = []
        base_ts = 1000000000
        for i in range(5):
            ticks.append(create_test_tick(base_ts + i * 1000000000, 1, 100.0))
        for i in range(5, 10):
            ticks.append(create_test_tick(base_ts + i * 1000000000, 1, 110.0))
        
        write_test_data(self.test_file, ticks)
        
        # Buy 500 shares @ $100, sell @ $110
        result = run_backtest(self.test_file, [(2, 'BUY', 500), (7, 'SELL', 500)])
        
        expected_pnl = 500 * (110.0 - 100.0)  # $5,000
        expected_cash = self.initial_capital + expected_pnl
        
        print(f"Expected P&L: ${expected_pnl:,.2f}")
        print(f"Final Cash:   ${result['final_cash']:,.2f}")
        
        self.assertAlmostEqual(result['final_cash'], expected_cash, delta=50.0)
        
        print("✓ PASSED")


if __name__ == "__main__":
    print("="*60)
    print("FELIX ENGINE - POSITION & P&L TESTS")
    print("="*60)
    unittest.main(verbosity=2)