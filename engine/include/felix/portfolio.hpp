#pragma once

#include "felix/execution.hpp"
#include <vector>
#include <unordered_map>

namespace felix {

/**
 * Position - Section 4.2
 */
struct Position {
    double quantity = 0.0;
    double avg_price = 0.0;
    double realized_pnl = 0.0;
};

/**
 * Equity Point - Section 4.2
 */
struct EquityPoint {
    uint64_t timestamp = 0;
    double equity = 0.0;
    double cash = 0.0;
    double unrealized_pnl = 0.0;
};

/**
 * Portfolio - Section 4.2
 * 
 * Tracks:
 * - Positions per symbol (long/short, average price)
 * - Cash, margin, equity
 * - Realized & unrealized P&L
 * - Equity curve for analytics
 */
class Portfolio {
public:
    explicit Portfolio(double initial_cash);
    
    // Fill processing
    void on_fill(const Fill& fill);
    
    // Price updates for mark-to-market
    void update_prices(uint64_t symbol_id, double price);
    
    // Equity tracking - Section 8.4
    void append_equity_point(uint64_t timestamp);
    
    // Accessors
    double cash() const { return cash_; }
    double initial_cash() const { return initial_cash_; }
    double equity() const;
    double unrealized_pnl(uint64_t symbol_id, double current_price) const;
    double total_unrealized_pnl() const;
    double total_realized_pnl() const;
    
    const Position& get_position(uint64_t symbol_id) const;
    const std::vector<EquityPoint>& equity_curve() const { return equity_curve_; }
    
    // For Python bindings - vectorized access
    std::vector<uint64_t> get_timestamps() const;
    std::vector<double> get_equity_values() const;

private:
    double cash_;
    double initial_cash_;
    std::unordered_map<uint64_t, Position> positions_;
    std::unordered_map<uint64_t, double> last_prices_;
    std::vector<EquityPoint> equity_curve_;
};

} // namespace felix