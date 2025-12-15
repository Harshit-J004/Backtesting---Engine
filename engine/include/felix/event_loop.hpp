#pragma once

#include "felix/datastream.hpp"
#include "felix/matching.hpp"
#include "felix/portfolio.hpp"
#include "felix/risk.hpp"
#include "felix/tick_record.hpp"
#include <functional>
#include <memory>

namespace felix {

// Forward declare strategy wrapper
class StrategyWrapper;

/**
 * Event Loop - Section 5.2 of design.txt
 * 
 * Core loop (single thread, per backtest):
 * - Deterministic: single thread, fixed random seed, strict timestamp order
 * - Risk before strategy: internal exits happen even if Python is slow
 */
class EventLoop {
public:
    EventLoop();
    ~EventLoop();

    // Set components
    void set_matching_engine(MatchingEngine* engine);
    void set_portfolio(Portfolio* portfolio);
    void set_risk_engine(RiskEngine* risk_engine);

    // Run the backtest - processes all events in order
    void run(DataStream& stream, StrategyWrapper& strategy);

    // Statistics
    uint64_t ticks_processed() const { return ticks_processed_; }
    uint64_t orders_processed() const { return orders_processed_; }
    uint64_t fills_generated() const { return fills_generated_; }

private:
    // Process a single tick event
    void process_tick(const TickRecord& tick, StrategyWrapper& strategy);
    
    // Check and execute pending orders against current market state
    void check_pending_orders(const TickRecord& tick, StrategyWrapper& strategy);
    
    // Update portfolio mark-to-market
    void update_portfolio_mtm(const TickRecord& tick);
    
    // Check risk limits and handle violations
    void check_risk_limits(StrategyWrapper& strategy);

    MatchingEngine* matching_engine_ = nullptr;
    Portfolio* portfolio_ = nullptr;
    RiskEngine* risk_engine_ = nullptr;

    uint64_t ticks_processed_ = 0;
    uint64_t orders_processed_ = 0;
    uint64_t fills_generated_ = 0;
    
    double peak_equity_ = 0.0;
    bool risk_halted_ = false;
};

/**
 * Strategy Wrapper - Bridges Python strategy to C++ engine
 * Section 7 of design.txt
 */
class StrategyWrapper {
public:
    virtual ~StrategyWrapper() = default;
    
    virtual void on_start() = 0;
    virtual void on_tick(const TickRecord& tick) = 0;
    virtual void on_bar(const TickRecord& bar) = 0;
    virtual void on_fill(const Fill& fill) = 0;
    virtual void on_end() = 0;
    
    // Check if strategy wants to wake on this tick
    virtual bool should_wake(const TickRecord& tick) { return true; }
    
    // Flag for risk halt
    bool is_halted() const { return halted_; }
    void set_halted(bool h) { halted_ = h; }

private:
    bool halted_ = false;
};

} // namespace felix