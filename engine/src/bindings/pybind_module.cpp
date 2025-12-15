#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>

#include "felix/tick_record.hpp"
#include "felix/execution.hpp"
#include "felix/portfolio.hpp"
#include "felix/matching.hpp"
#include "felix/risk.hpp"
#include "felix/datastream.hpp"
#include "felix/event_loop.hpp"

namespace py = pybind11;

namespace felix {

/**
 * Python Strategy Wrapper - Section 7
 * Bridges Python strategy class to C++ StrategyWrapper interface
 */
class PyStrategyWrapper : public StrategyWrapper {
public:
    PyStrategyWrapper(py::object strategy, MatchingEngine* engine, Portfolio* portfolio) 
        : py_strategy_(strategy), engine_(engine), portfolio_(portfolio) {}
    
    void on_start() override {
        py::gil_scoped_acquire acquire;
        if (py::hasattr(py_strategy_, "on_start")) {
            py_strategy_.attr("on_start")();
        }
    }
    
    void on_tick(const TickRecord& tick) override {
        py::gil_scoped_acquire acquire;
        if (py::hasattr(py_strategy_, "on_tick")) {
            py_strategy_.attr("on_tick")(tick);
        }
    }
    
    void on_bar(const TickRecord& bar) override {
        py::gil_scoped_acquire acquire;
        if (py::hasattr(py_strategy_, "on_bar")) {
            py_strategy_.attr("on_bar")(bar);
        }
    }
    
    void on_fill(const Fill& fill) override {
        py::gil_scoped_acquire acquire;
        if (py::hasattr(py_strategy_, "on_fill")) {
            py_strategy_.attr("on_fill")(fill);
        }
    }
    
    void on_end() override {
        py::gil_scoped_acquire acquire;
        if (py::hasattr(py_strategy_, "on_end")) {
            py_strategy_.attr("on_end")();
        }
    }
    
    MatchingEngine* get_engine() { return engine_; }
    Portfolio* get_portfolio() { return portfolio_; }

private:
    py::object py_strategy_;
    MatchingEngine* engine_;
    Portfolio* portfolio_;
};

} // namespace felix

PYBIND11_MODULE(felix_engine, m) {
    m.doc() = "Felix Backtesting Engine - C++ Core (design.txt compliant)";

    // ========== ENUMS ==========
    py::enum_<felix::Side>(m, "Side")
        .value("BUY", felix::Side::BUY)
        .value("SELL", felix::Side::SELL);

    py::enum_<felix::OrderType>(m, "OrderType")
        .value("MARKET", felix::OrderType::MARKET)
        .value("LIMIT", felix::OrderType::LIMIT)
        .value("STOP", felix::OrderType::STOP)
        .value("STOP_LIMIT", felix::OrderType::STOP_LIMIT);

    py::enum_<felix::OrderStatus>(m, "OrderStatus")
        .value("PENDING", felix::OrderStatus::PENDING)
        .value("ACTIVE", felix::OrderStatus::ACTIVE)
        .value("PARTIAL", felix::OrderStatus::PARTIAL)
        .value("FILLED", felix::OrderStatus::FILLED)
        .value("CANCELLED", felix::OrderStatus::CANCELLED)
        .value("REJECTED", felix::OrderStatus::REJECTED);

    // ========== DATA STRUCTURES ==========
    
    // TickRecord - Section 4.1
    py::class_<felix::TickRecord>(m, "TickRecord")
        .def(py::init<>())
        .def_readwrite("timestamp", &felix::TickRecord::timestamp)
        .def_readwrite("symbol_id", &felix::TickRecord::symbol_id)
        .def_readwrite("price", &felix::TickRecord::price)
        .def_readwrite("bid", &felix::TickRecord::bid)
        .def_readwrite("ask", &felix::TickRecord::ask)
        .def_readwrite("bid_size", &felix::TickRecord::bid_size)
        .def_readwrite("ask_size", &felix::TickRecord::ask_size)
        .def_readwrite("volume", &felix::TickRecord::volume)
        .def("__repr__", [](const felix::TickRecord& t) {
            return "<TickRecord ts=" + std::to_string(t.timestamp) + 
                   " price=" + std::to_string(t.price) + ">";
        });

    // Fill - Section 6.3
    py::class_<felix::Fill>(m, "Fill")
        .def(py::init<>())
        .def_readwrite("order_id", &felix::Fill::order_id)
        .def_readwrite("symbol_id", &felix::Fill::symbol_id)
        .def_readwrite("side", &felix::Fill::side)
        .def_readwrite("price", &felix::Fill::price)
        .def_readwrite("volume", &felix::Fill::volume)
        .def_readwrite("timestamp", &felix::Fill::timestamp)
        .def_readwrite("slippage", &felix::Fill::slippage)
        .def("__repr__", [](const felix::Fill& f) {
            return "<Fill order=" + std::to_string(f.order_id) + 
                   " price=" + std::to_string(f.price) + 
                   " vol=" + std::to_string(f.volume) + ">";
        });

    // Order - Section 6.1
    py::class_<felix::Order>(m, "Order")
        .def(py::init<>())
        .def_readwrite("order_id", &felix::Order::order_id)
        .def_readwrite("symbol_id", &felix::Order::symbol_id)
        .def_readwrite("side", &felix::Order::side)
        .def_readwrite("order_type", &felix::Order::order_type)
        .def_readwrite("price", &felix::Order::price)
        .def_readwrite("size", &felix::Order::size)
        .def_readwrite("timestamp", &felix::Order::timestamp)
        .def_readwrite("status", &felix::Order::status)
        .def("__repr__", [](const felix::Order& o) {
            return "<Order id=" + std::to_string(o.order_id) + 
                   " size=" + std::to_string(o.size) + ">";
        });

    // Position - Section 4.2
    py::class_<felix::Position>(m, "Position")
        .def(py::init<>())
        .def_readonly("quantity", &felix::Position::quantity)
        .def_readonly("avg_price", &felix::Position::avg_price)
        .def_readonly("realized_pnl", &felix::Position::realized_pnl);

    // EquityPoint - Section 4.2
    py::class_<felix::EquityPoint>(m, "EquityPoint")
        .def(py::init<>())
        .def_readonly("timestamp", &felix::EquityPoint::timestamp)
        .def_readonly("equity", &felix::EquityPoint::equity)
        .def_readonly("cash", &felix::EquityPoint::cash)
        .def_readonly("unrealized_pnl", &felix::EquityPoint::unrealized_pnl);

    // ========== CONFIGURATION ==========
    
    // SlippageConfig - Section 8.3
    py::class_<felix::SlippageConfig>(m, "SlippageConfig")
        .def(py::init<>())
        .def_readwrite("fixed_bps", &felix::SlippageConfig::fixed_bps)
        .def_readwrite("volatility_mult", &felix::SlippageConfig::volatility_mult)
        .def_readwrite("size_impact", &felix::SlippageConfig::size_impact)
        .def_readwrite("use_stochastic", &felix::SlippageConfig::use_stochastic)
        .def_readwrite("stochastic_std", &felix::SlippageConfig::stochastic_std);

    // LatencyConfig - Section 8.1
    py::class_<felix::LatencyConfig>(m, "LatencyConfig")
        .def(py::init<>())
        .def_readwrite("strategy_latency_ns", &felix::LatencyConfig::strategy_latency_ns)
        .def_readwrite("engine_latency_ns", &felix::LatencyConfig::engine_latency_ns);

    // RiskLimits - Section 8.4
    py::class_<felix::RiskLimits>(m, "RiskLimits")
        .def(py::init<>())
        .def_readwrite("max_drawdown", &felix::RiskLimits::max_drawdown)
        .def_readwrite("max_position_size", &felix::RiskLimits::max_position_size)
        .def_readwrite("max_order_size", &felix::RiskLimits::max_order_size)
        .def_readwrite("max_notional", &felix::RiskLimits::max_notional)
        .def_readwrite("max_daily_loss", &felix::RiskLimits::max_daily_loss);

    // ========== CORE COMPONENTS ==========
    
    // Portfolio - Section 4.2
    py::class_<felix::Portfolio>(m, "Portfolio")
        .def(py::init<double>(), py::arg("initial_cash"))
        .def("on_fill", &felix::Portfolio::on_fill)
        .def("update_prices", &felix::Portfolio::update_prices)
        .def("append_equity_point", &felix::Portfolio::append_equity_point)
        .def("cash", &felix::Portfolio::cash)
        .def("initial_cash", &felix::Portfolio::initial_cash)
        .def("equity", &felix::Portfolio::equity)
        .def("total_unrealized_pnl", &felix::Portfolio::total_unrealized_pnl)
        .def("total_realized_pnl", &felix::Portfolio::total_realized_pnl)
        .def("get_position", &felix::Portfolio::get_position, py::return_value_policy::reference)
        .def("equity_curve", &felix::Portfolio::equity_curve, py::return_value_policy::reference)
        .def("get_timestamps", &felix::Portfolio::get_timestamps)
        .def("get_equity_values", &felix::Portfolio::get_equity_values);

    // MatchingEngine - Section 6
    py::class_<felix::MatchingEngine>(m, "MatchingEngine")
        .def(py::init<const felix::SlippageConfig&>(), py::arg("slippage") = felix::SlippageConfig{})
        .def("set_latency_config", &felix::MatchingEngine::set_latency_config)
        .def("set_slippage_config", &felix::MatchingEngine::set_slippage_config)
        .def("update_market_state", &felix::MatchingEngine::update_market_state)
        .def("submit_order", &felix::MatchingEngine::submit_order)
        .def("cancel_order", &felix::MatchingEngine::cancel_order)
        .def("process_pending_orders", &felix::MatchingEngine::process_pending_orders,
             py::return_value_policy::move)
        .def("get_best_bid", &felix::MatchingEngine::get_best_bid)
        .def("get_best_ask", &felix::MatchingEngine::get_best_ask)
        .def("get_last_price", &felix::MatchingEngine::get_last_price)
        .def("pending_order_count", &felix::MatchingEngine::pending_order_count)
        .def("get_pending_orders", &felix::MatchingEngine::get_pending_orders,
             py::return_value_policy::reference);

    // RiskEngine - Section 8.4
    py::class_<felix::RiskEngine>(m, "RiskEngine")
        .def(py::init<const felix::RiskLimits&>(), py::arg("limits"))
        .def("check_order", &felix::RiskEngine::check_order)
        .def("check_drawdown", &felix::RiskEngine::check_drawdown)
        .def("check_position_limit", &felix::RiskEngine::check_position_limit)
        .def("is_halted", &felix::RiskEngine::is_halted)
        .def("halt", &felix::RiskEngine::halt)
        .def("reset", &felix::RiskEngine::reset);

    // DataStream - Section 4.1
    py::class_<felix::DataStream>(m, "DataStream")
        .def(py::init<>())
        .def("load", &felix::DataStream::load)
        .def("size", &felix::DataStream::size)
        .def("has_next", &felix::DataStream::has_next)
        .def("next", &felix::DataStream::next, py::return_value_policy::reference)
        .def("peek", &felix::DataStream::peek, py::return_value_policy::reference)
        .def("reset", &felix::DataStream::reset)
        .def("current_index", &felix::DataStream::current_index);

    // ========== EVENT LOOP - Section 5.2 ==========
    py::class_<felix::EventLoop>(m, "EventLoop")
        .def(py::init<>())
        .def("set_matching_engine", &felix::EventLoop::set_matching_engine)
        .def("set_portfolio", &felix::EventLoop::set_portfolio)
        .def("set_risk_engine", &felix::EventLoop::set_risk_engine)
        .def("ticks_processed", &felix::EventLoop::ticks_processed)
        .def("orders_processed", &felix::EventLoop::orders_processed)
        .def("fills_generated", &felix::EventLoop::fills_generated)
        // Main run method that takes Python strategy
        .def("run", [](felix::EventLoop& loop, felix::DataStream& stream, 
                       py::object py_strategy, felix::MatchingEngine* engine,
                       felix::Portfolio* portfolio) {
            // Create wrapper that bridges Python to C++
            felix::PyStrategyWrapper wrapper(py_strategy, engine, portfolio);
            
            // Release GIL during C++ processing for better performance
            {
                py::gil_scoped_release release;
                loop.run(stream, wrapper);
            }
        }, py::arg("stream"), py::arg("strategy"), py::arg("engine"), py::arg("portfolio"));

    // ========== UTILITY FUNCTIONS ==========
    m.def("create_market_order", [](uint32_t symbol_id, felix::Side side, double size, 
                                     uint64_t timestamp) {
        felix::Order order;
        order.symbol_id = symbol_id;
        order.side = side;
        order.order_type = felix::OrderType::MARKET;
        order.size = size;
        order.timestamp = timestamp;
        order.price = 0.0;  // Market orders don't need price
        return order;
    }, py::arg("symbol_id"), py::arg("side"), py::arg("size"), py::arg("timestamp"));

    m.def("create_limit_order", [](uint32_t symbol_id, felix::Side side, double size,
                                    double price, uint64_t timestamp) {
        felix::Order order;
        order.symbol_id = symbol_id;
        order.side = side;
        order.order_type = felix::OrderType::LIMIT;
        order.size = size;
        order.price = price;
        order.timestamp = timestamp;
        return order;
    }, py::arg("symbol_id"), py::arg("side"), py::arg("size"), 
       py::arg("price"), py::arg("timestamp"));
}