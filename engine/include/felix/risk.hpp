#pragma once

#include "felix/execution.hpp"
#include "felix/portfolio.hpp"

namespace felix {

/**
 * Risk Limits - Section 8.4
 */
struct RiskLimits {
    double max_drawdown = 0.20;       // Maximum drawdown (20% default)
    double max_position_size = 1000;   // Maximum position per symbol
    double max_order_size = 500;       // Maximum single order size
    double max_notional = 0;           // Maximum notional value (0 = unlimited)
    double max_daily_loss = 0;         // Maximum daily loss (0 = unlimited)
};

/**
 * Risk Engine - Section 8.4
 */
class RiskEngine {
public:
    explicit RiskEngine(const RiskLimits& limits);
    
    // Pre-trade checks
    bool check_order(const Order& order, const Portfolio& portfolio);
    bool check_drawdown(const Portfolio& portfolio, double peak_equity);
    bool check_position_limit(const Portfolio& portfolio, uint32_t symbol_id, double proposed_size);
    bool check_daily_loss(double pnl_change);
    
    // State management
    void halt();
    void reset();
    void reset_daily();
    bool is_halted() const;
    
    const RiskLimits& limits() const { return limits_; }

private:
    RiskLimits limits_;
    bool halted_;
    double daily_pnl_;
    uint64_t last_day_;
};

} // namespace felix