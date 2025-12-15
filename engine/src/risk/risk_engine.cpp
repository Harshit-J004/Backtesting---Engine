#include "felix/risk.hpp"
#include <cmath>
#include <iostream>

namespace felix {

RiskEngine::RiskEngine(const RiskLimits& limits)
    : limits_(limits)
    , halted_(false)
    , daily_pnl_(0.0)
    , last_day_(0) {}

bool RiskEngine::check_order(const Order& order, const Portfolio& portfolio) {
    /**
     * Section 8.4 - Pre-trade Risk Checks
     */
    
    if (halted_) {
        std::cout << "[Risk] REJECTED: System halted" << std::endl;
        return false;
    }
    
    // Check order size limit
    if (order.size > limits_.max_order_size) {
        std::cout << "[Risk] REJECTED: Order size " << order.size 
                  << " exceeds max " << limits_.max_order_size << std::endl;
        return false;
    }
    
    // Check position limit
    const Position& pos = portfolio.get_position(order.symbol_id);
    double new_position = pos.quantity;
    
    if (order.side == Side::BUY) {
        new_position += order.size;
    } else {
        new_position -= order.size;
    }
    
    if (std::abs(new_position) > limits_.max_position_size) {
        std::cout << "[Risk] REJECTED: Position " << new_position 
                  << " would exceed max " << limits_.max_position_size << std::endl;
        return false;
    }
    
    // Check notional limit
    double notional = order.size * order.price;
    if (notional > limits_.max_notional && limits_.max_notional > 0) {
        std::cout << "[Risk] REJECTED: Notional " << notional 
                  << " exceeds max " << limits_.max_notional << std::endl;
        return false;
    }
    
    return true;
}

bool RiskEngine::check_drawdown(const Portfolio& portfolio, double peak_equity) {
    /**
     * Section 8.4 - Drawdown Check
     */
    
    if (halted_) return false;
    
    double current_equity = portfolio.equity();
    double drawdown = (peak_equity - current_equity) / peak_equity;
    
    if (drawdown > limits_.max_drawdown) {
        return false;
    }
    
    return true;
}

bool RiskEngine::check_position_limit(const Portfolio& portfolio, uint32_t symbol_id, double proposed_size) {
    /**
     * Section 8.4 - Position Limit Check
     */
    
    const Position& pos = portfolio.get_position(symbol_id);
    double total_position = std::abs(pos.quantity) + std::abs(proposed_size);
    
    return total_position <= limits_.max_position_size;
}

bool RiskEngine::check_daily_loss(double pnl_change) {
    /**
     * Section 8.4 - Daily Loss Limit
     */
    
    daily_pnl_ += pnl_change;
    
    if (daily_pnl_ < -limits_.max_daily_loss && limits_.max_daily_loss > 0) {
        std::cout << "[Risk] Daily loss limit exceeded: " << daily_pnl_ << std::endl;
        return false;
    }
    
    return true;
}

void RiskEngine::reset_daily() {
    daily_pnl_ = 0.0;
}

void RiskEngine::halt() {
    halted_ = true;
    std::cout << "[Risk] System HALTED" << std::endl;
}

void RiskEngine::reset() {
    halted_ = false;
    daily_pnl_ = 0.0;
}

bool RiskEngine::is_halted() const {
    return halted_;
}

} // namespace felix