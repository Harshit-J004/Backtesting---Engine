#include "felix/risk.hpp"
#include <cmath>
#include <iostream>

namespace felix {

RiskEngine::RiskEngine(const RiskLimits& limits)
    : limits_(limits)
    , halted_(false)
    , daily_pnl_(0.0)
    , last_day_(0) {}

bool RiskEngine::check_order(const Order& order, double portfolio_cash, double current_equity, double initial_cash) const {
    /**
     * Section 8.4 - Pre-trade Risk Checks
     * Only checks that can be done with primitive values passed in.
     * Position limits are checked separately via check_position_limit().
     */
    
    if (halted_) {
        std::cout << "[Risk] REJECTED: System halted" << std::endl;
        return false;
    }
    
    double notional = order.price * order.size;
    
    // Check order size limit
    if (order.size > limits_.max_order_size) {
        std::cout << "[Risk] REJECTED: Order size " << order.size 
                  << " exceeds max " << limits_.max_order_size << std::endl;
        return false;
    }
    
    // Check notional limit
    if (notional > limits_.max_notional && limits_.max_notional > 0) {
        std::cout << "[Risk] REJECTED: Notional " << notional 
                  << " exceeds max " << limits_.max_notional << std::endl;
        return false;
    }
    
    // Check cash for BUY orders
    if (order.side == Side::BUY) {
        if (notional > portfolio_cash) {
            std::cout << "[Risk] REJECTED: Insufficient cash. Need " << notional 
                      << ", have " << portfolio_cash << std::endl;
            return false;
        }
    }
    
    return true;
}

void RiskEngine::check_and_update_halt(double current_equity, double initial_capital, double daily_pnl) {
    if (halted_) return;  // Already halted
    
    // Update peak equity
    if (current_equity > peak_equity_) {
        peak_equity_ = current_equity;
    }
    
    // Initialize peak if zero
    if (peak_equity_ <= 0.0) {
        peak_equity_ = initial_capital;
    }
    
    // Check max drawdown
    if (peak_equity_ > 0) {
        double drawdown = (peak_equity_ - current_equity) / peak_equity_;
        if (drawdown > limits_.max_drawdown) {
            halted_ = true;
            std::cout << "[RISK] Max drawdown exceeded! Halting strategy." << std::endl;
            return;
        }
    }
    
    // Check max daily loss
    if (daily_pnl < -limits_.max_daily_loss && limits_.max_daily_loss > 0) {
        halted_ = true;
        std::cout << "[RISK] Max daily loss exceeded! Halting strategy." << std::endl;
        return;
    }
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

// bool RiskEngine::is_halted() const {
//     return halted_;
// }

} // namespace felix