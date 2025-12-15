#pragma once

#include "felix/execution.hpp"
#include "felix/tick_record.hpp"
#include <vector>
#include <unordered_map>
#include <random>

namespace felix {

/**
 * Slippage Configuration - Section 8.3
 */
struct SlippageConfig {
    double fixed_bps = 0.0;           // Fixed slippage in basis points
    double volatility_mult = 0.0;      // Multiplier for volatility-based slippage
    double size_impact = 0.0;          // Impact of order size
    bool use_stochastic = false;       // Enable random slippage component
    double stochastic_std = 0.0;       // Std dev for stochastic slippage
};

/**
 * Latency Configuration - Section 8.1
 */
struct LatencyConfig {
    uint64_t strategy_latency_ns = 0;  // Time from signal to order submission
    uint64_t engine_latency_ns = 0;    // Time from submission to activation
};

/**
 * Market State - Current state for a symbol
 */
struct MarketState {
    double last_price = 0.0;
    double bid = 0.0;
    double ask = 0.0;
    double bid_size = 0.0;
    double ask_size = 0.0;
    uint64_t last_timestamp = 0;
};

/**
 * Matching Engine - Section 6
 * 
 * Handles order matching with:
 * - Latency modeling (Section 8.1)
 * - Slippage modeling (Section 8.3)
 * - Queue position simulation (Section 6.2)
 */
class MatchingEngine {
public:
    explicit MatchingEngine(const SlippageConfig& slippage = SlippageConfig{});
    
    // Configuration
    void set_latency_config(const LatencyConfig& config);
    void set_slippage_config(const SlippageConfig& config);
    
    // Market state updates
    void update_market_state(const TickRecord& tick);
    
    // Order management
    uint64_t submit_order(Order order);
    bool cancel_order(uint64_t order_id);
    
    // Order processing - returns fills
    std::vector<Fill> process_pending_orders(uint64_t current_timestamp);
    
    // Market data queries
    double get_best_bid(uint32_t symbol_id) const;
    double get_best_ask(uint32_t symbol_id) const;
    double get_last_price(uint32_t symbol_id) const;
    
    // Order book queries
    size_t pending_order_count() const;
    const std::vector<Order>& get_pending_orders() const;

private:
    // Order matching functions
    bool match_market_order(const Order& order, const MarketState& market, Fill& fill);
    bool match_limit_order(const Order& order, const MarketState& market, Fill& fill);
    bool match_stop_order(const Order& order, const MarketState& market, Fill& fill);
    
    // Apply slippage to fill
    void apply_slippage(Fill& fill, const Order& order, const MarketState& market);
    
    // Configuration
    SlippageConfig slippage_config_;
    LatencyConfig latency_config_;
    
    // State
    std::unordered_map<uint32_t, MarketState> market_states_;
    std::vector<Order> pending_orders_;
    uint64_t next_order_id_;
    
    // Random generator for stochastic slippage
    mutable std::mt19937 rng_;
};

} // namespace felix