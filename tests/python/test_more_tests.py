import os
import sys
import struct
import unittest

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "python"))

import felix_engine as fe
from felix.strategy.base import Strategy

TICK_FORMAT = "<QIfffffII"
TICK_SIZE = 40


def create_test_tick(timestamp_ns: int, symbol_id: int, price: float, volume: int = 100000):
    bid = price
    ask = price
    return struct.pack(TICK_FORMAT, timestamp_ns, symbol_id, price, bid, ask, 100.0, 100.0, volume, 0)


def write_test_data(filepath: str, ticks):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "wb") as f:
        for t in ticks:
            f.write(t)


def make_engine_portfolio_risk(
    initial_capital=100000.0,
    *,
    slippage_bps=0.0,
    strategy_latency_ns=0,
    engine_latency_ns=0,
    max_drawdown=1.0,
    max_position_size=100000,
    max_order_size=100000,
    max_notional=1e12,
    max_daily_loss=1e12,
):
    slippage = fe.SlippageConfig()
    slippage.fixed_bps = float(slippage_bps)

    latency = fe.LatencyConfig()
    latency.strategy_latency_ns = int(strategy_latency_ns)
    latency.engine_latency_ns = int(engine_latency_ns)

    engine = fe.MatchingEngine(slippage)
    engine.set_latency_config(latency)

    portfolio = fe.Portfolio(float(initial_capital))

    limits = fe.RiskLimits()
    limits.max_drawdown = float(max_drawdown)
    limits.max_position_size = int(max_position_size)
    limits.max_order_size = int(max_order_size)
    limits.max_notional = float(max_notional)
    limits.max_daily_loss = float(max_daily_loss)

    risk_engine = fe.RiskEngine(limits)
    return engine, portfolio, risk_engine


class ScriptedOrdersStrategy(Strategy):
    def __init__(self, engine, portfolio, order_plan):
        self.engine = engine
        self.portfolio = portfolio
        self.order_plan = order_plan  # list of dicts: {tick, side, size, symbol_id(optional)}
        self.tick_count = 0
        self.fills = []

    def on_start(self):
        pass

    def on_tick(self, tick):
        self.tick_count += 1
        for o in self.order_plan:
            if o["tick"] != self.tick_count:
                continue
            order = fe.Order()
            order.symbol_id = int(o.get("symbol_id", tick.symbol_id))
            order.side = fe.Side.BUY if o["side"] == "BUY" else fe.Side.SELL
            order.order_type = fe.OrderType.MARKET
            order.size = int(o["size"])
            order.price = float(tick.price)
            order.timestamp = int(tick.timestamp)
            self.engine.submit_order(order)

    def on_fill(self, fill):
        self.fills.append(fill)

    def on_bar(self, bar):
        pass

    def on_end(self):
        pass


class AlwaysTradeAfterExitStrategy(Strategy):
    """
    Used for risk-halt tests:
    - Enters once
    - Exits once (to realize loss)
    - Then repeatedly tries to re-enter every tick (should be blocked after HALT)
    """
    def __init__(self, engine, portfolio, entry_tick, exit_tick, size):
        self.engine = engine
        self.portfolio = portfolio
        self.entry_tick = entry_tick
        self.exit_tick = exit_tick
        self.size = size
        self.tick_count = 0
        self.fills = []

    def on_start(self):
        pass

    def on_tick(self, tick):
        self.tick_count += 1

        if self.tick_count == self.entry_tick:
            self._submit(tick, "BUY", self.size)

        if self.tick_count == self.exit_tick:
            self._submit(tick, "SELL", self.size)

        if self.tick_count > self.exit_tick:
            self._submit(tick, "BUY", self.size)

    def _submit(self, tick, side, size):
        order = fe.Order()
        order.symbol_id = int(tick.symbol_id)
        order.side = fe.Side.BUY if side == "BUY" else fe.Side.SELL
        order.order_type = fe.OrderType.MARKET
        order.size = int(size)
        order.price = float(tick.price)
        order.timestamp = int(tick.timestamp)
        self.engine.submit_order(order)

    def on_fill(self, fill):
        self.fills.append(fill)

    def on_bar(self, bar):
        pass

    def on_end(self):
        pass


def run_stream(engine, portfolio, risk_engine, stream_file, strategy):
    stream = fe.DataStream()
    stream.load(stream_file)

    loop = fe.EventLoop()
    loop.set_matching_engine(engine)
    loop.set_portfolio(portfolio)
    loop.set_risk_engine(risk_engine)
    loop.run(stream, strategy, engine, portfolio)

    return {
        "portfolio": portfolio,
        "strategy": strategy,
        "final_cash": portfolio.cash(),
        "final_equity": portfolio.equity(),
        "fills": getattr(strategy, "fills", []),
        "equity_curve": portfolio.get_equity_values(),
        "timestamps": portfolio.get_timestamps(),
        "ticks_processed": loop.ticks_processed(),
        "orders_processed": loop.orders_processed(),
        "fills_generated": loop.fills_generated(),
    }


class TestMoreCriticalCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_data_dir = os.path.join(project_root, "data", "test")
        os.makedirs(cls.test_data_dir, exist_ok=True)

    def test_01_insufficient_cash_rejects_buy(self):
        test_file = os.path.join(self.test_data_dir, "more_insufficient_cash.bin")
        ticks = [create_test_tick(1_000_000_000 * (i + 1), 1, 100.0) for i in range(5)]
        write_test_data(test_file, ticks)

        engine, portfolio, risk_engine = make_engine_portfolio_risk(
            initial_capital=1000.0,
            max_notional=1e12,
            max_daily_loss=1e12,
            max_drawdown=1.0,
        )

        strat = ScriptedOrdersStrategy(engine, portfolio, [{"tick": 2, "side": "BUY", "size": 20}])  # costs 2000
        res = run_stream(engine, portfolio, risk_engine, test_file, strat)

        self.assertEqual(len(res["fills"]), 0, "Order should not fill when cash is insufficient")
        self.assertAlmostEqual(res["final_cash"], 1000.0, delta=1e-6)
        self.assertAlmostEqual(res["final_equity"], 1000.0, delta=1e-6)

    def test_02_max_notional_rejects_order(self):
        test_file = os.path.join(self.test_data_dir, "more_max_notional.bin")
        ticks = [create_test_tick(1_000_000_000 * (i + 1), 1, 100.0) for i in range(5)]
        write_test_data(test_file, ticks)

        engine, portfolio, risk_engine = make_engine_portfolio_risk(
            initial_capital=10_000.0,
            max_notional=500.0,  # very small
        )

        strat = ScriptedOrdersStrategy(engine, portfolio, [{"tick": 2, "side": "BUY", "size": 10}])  # notional 1000
        res = run_stream(engine, portfolio, risk_engine, test_file, strat)

        self.assertEqual(len(res["fills"]), 0, "Order should be rejected by max_notional")

    def test_03_max_order_size_caps_or_rejects(self):
        test_file = os.path.join(self.test_data_dir, "more_max_order_size.bin")
        ticks = [create_test_tick(1_000_000_000 * (i + 1), 1, 50.0) for i in range(5)]
        write_test_data(test_file, ticks)

        engine, portfolio, risk_engine = make_engine_portfolio_risk(
            initial_capital=10_000.0,
            max_order_size=5,
            max_position_size=5,
            max_notional=1e12,
        )

        strat = ScriptedOrdersStrategy(engine, portfolio, [{"tick": 2, "side": "BUY", "size": 10}])
        res = run_stream(engine, portfolio, risk_engine, test_file, strat)

        if len(res["fills"]) == 0:
            self.assertTrue(True)  # rejected is acceptable
        else:
            self.assertLessEqual(int(res["fills"][0].volume), 5, "If filled, must be capped to max_order_size")

    def test_04_max_daily_loss_halts_further_trading(self):
        test_file = os.path.join(self.test_data_dir, "more_daily_loss_halt.bin")
        # Buy at 100, sell at 50 => realized loss 500 on size 10
        prices = [100.0, 100.0, 50.0, 100.0, 100.0, 100.0]
        ticks = [create_test_tick(1_000_000_000 * (i + 1), 1, prices[i]) for i in range(len(prices))]
        write_test_data(test_file, ticks)

        engine, portfolio, risk_engine = make_engine_portfolio_risk(
            initial_capital=10_000.0,
            max_daily_loss=100.0,  # exceed after loss
            max_drawdown=1.0,
            max_notional=1e12,
            max_order_size=1000,
            max_position_size=1000,
        )

        strat = AlwaysTradeAfterExitStrategy(engine, portfolio, entry_tick=2, exit_tick=3, size=10)
        res = run_stream(engine, portfolio, risk_engine, test_file, strat)

        self.assertGreaterEqual(len(res["fills"]), 2, "Entry and exit should fill")
        self.assertEqual(len(res["fills"]), 2, "After daily loss HALT, further orders must not fill")


    def test_05_latency_delays_fill_until_active(self):
        test_file = os.path.join(self.test_data_dir, "more_latency.bin")
        # t=0 price=100, t=100 price=200, t=200 price=300
        ticks = [
            create_test_tick(0, 1, 100.0),
            create_test_tick(100, 1, 200.0),
            create_test_tick(200, 1, 300.0),
            create_test_tick(300, 1, 400.0),
        ]
        write_test_data(test_file, ticks)

        engine, portfolio, risk_engine = make_engine_portfolio_risk(
            initial_capital=1_000_000.0,
            strategy_latency_ns=100,
            engine_latency_ns=50,  # active at t + 150
            max_notional=1e12,
        )

        strat = ScriptedOrdersStrategy(engine, portfolio, [{"tick": 1, "side": "BUY", "size": 1}])
        res = run_stream(engine, portfolio, risk_engine, test_file, strat)

        self.assertEqual(len(res["fills"]), 1)
        fill_price = float(res["fills"][0].price)
        self.assertEqual(fill_price, 300.0, "Order should become active at t>=150, filling on tick at t=200")

    def test_06_slippage_direction_buy_vs_sell(self):
        test_file = os.path.join(self.test_data_dir, "more_slippage_direction.bin")
        ticks = [create_test_tick(1_000_000_000 * (i + 1), 1, 100.0) for i in range(6)]
        write_test_data(test_file, ticks)

        engine, portfolio, risk_engine = make_engine_portfolio_risk(
            initial_capital=100_000.0,
            slippage_bps=10.0,
            max_notional=1e12,
        )

        strat = ScriptedOrdersStrategy(
            engine,
            portfolio,
            [{"tick": 2, "side": "BUY", "size": 10}, {"tick": 4, "side": "SELL", "size": 10}],
        )
        res = run_stream(engine, portfolio, risk_engine, test_file, strat)

        self.assertEqual(len(res["fills"]), 2)
        buy_fill = res["fills"][0]
        sell_fill = res["fills"][1]
        self.assertGreaterEqual(float(buy_fill.price), 100.0)
        self.assertLessEqual(float(sell_fill.price), 100.0)

    def test_07_equity_curve_and_timestamps_consistency(self):
        test_file = os.path.join(self.test_data_dir, "more_equity_series.bin")
        ticks = [create_test_tick(1_000_000_000 * (i + 1), 1, 100.0 + i) for i in range(20)]
        write_test_data(test_file, ticks)

        engine, portfolio, risk_engine = make_engine_portfolio_risk(initial_capital=10_000.0)

        strat = ScriptedOrdersStrategy(engine, portfolio, [{"tick": 2, "side": "BUY", "size": 10}])
        res = run_stream(engine, portfolio, risk_engine, test_file, strat)

        eq = res["equity_curve"]
        ts = res["timestamps"]
        self.assertTrue(len(eq) > 0)
        self.assertEqual(len(eq), len(ts), "Equity series and timestamps must align")
        self.assertTrue(all(ts[i] <= ts[i + 1] for i in range(len(ts) - 1)), "Timestamps must be non-decreasing")

    def test_08_multiple_orders_same_tick_all_fill(self):
        test_file = os.path.join(self.test_data_dir, "more_multi_orders.bin")
        ticks = [create_test_tick(1_000_000_000 * (i + 1), 1, 100.0) for i in range(5)]
        write_test_data(test_file, ticks)

        engine, portfolio, risk_engine = make_engine_portfolio_risk(initial_capital=100_000.0)

        strat = ScriptedOrdersStrategy(
            engine,
            portfolio,
            [
                {"tick": 2, "side": "BUY", "size": 10},
                {"tick": 2, "side": "BUY", "size": 5},
            ],
        )
        res = run_stream(engine, portfolio, risk_engine, test_file, strat)

        self.assertEqual(len(res["fills"]), 2, "Both orders should fill")
        expected_cash = 100_000.0 - (15 * 100.0)
        self.assertAlmostEqual(res["final_cash"], expected_cash, delta=5.0)

    def test_9_risk_blocks_new_orders_after_halt_even_if_ticks_continue(self):
        test_file = os.path.join(self.test_data_dir, "more_halt_blocks_orders.bin")
        # Many ticks after the loss event to confirm no more fills occur
        prices = [100.0, 100.0, 50.0] + [100.0] * 20
        ticks = [create_test_tick(1_000_000_000 * (i + 1), 1, prices[i]) for i in range(len(prices))]
        write_test_data(test_file, ticks)

        engine, portfolio, risk_engine = make_engine_portfolio_risk(
            initial_capital=10_000.0,
            max_daily_loss=100.0,
            max_drawdown=1.0,
            max_notional=1e12,
        )

        strat = AlwaysTradeAfterExitStrategy(engine, portfolio, entry_tick=2, exit_tick=3, size=10)
        res = run_stream(engine, portfolio, risk_engine, test_file, strat)

        self.assertEqual(len(res["fills"]), 2)
        self.assertGreater(res["ticks_processed"], 3, "Event loop should keep processing ticks")
        self.assertEqual(res["fills_generated"], 2, "But no more fills should occur after HALT")


if __name__ == "__main__":
    unittest.main(verbosity=2)