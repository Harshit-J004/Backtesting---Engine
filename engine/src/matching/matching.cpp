#include "felix/matching.hpp"
#include <algorithm>
#include <cmath>
#include <random>
#include <iostream>

namespace felix {

MatchingEngine::MatchingEngine(const SlippageConfig& slippage)
    : slippage_config_(slippage)
    , next_order_id_(1) {
    // Initialize random generator for stochastic slippage
    std::random_device rd;
    rng_.seed(rd());
}

void MatchingEngine::set_latency_config(const LatencyConfig& config) {
    latency_config_ = config;
}

void MatchingEngine::set_slippage_config(const SlippageConfig& config) {
    slippage_config_ = config;
}

void MatchingEngine::update_market_state(const TickRecord& tick) {
    /**
     * Section 6 - Update market state from tick
     */
    MarketState& state = market_states_[tick.symbol_id];
    state.last_price = tick.price;
    state.bid = tick.bid;
    state.ask = tick.ask;
    state.bid_size = tick.bid_size;
    state.ask_size = tick.ask_size;
    state.last_timestamp = tick.timestamp;
}

uint64_t MatchingEngine::submit_order(Order order) {
    /**
     * Section 6.1 & 8.1 - Order Submission with Latency
     * 
     * t_active = t_signal + Δ_strategy + Δ_engine
     * Order becomes eligible for matching only when t >= t_active
     */
    
    // Assign order ID
    order.order_id = next_order_id_++;
    order.status = OrderStatus::PENDING;
    
    // Calculate activation time with latency model (Section 8.1)
    uint64_t total_latency = latency_config_.strategy_latency_ns + latency_config_.engine_latency_ns;
    order.activation_time = order.timestamp + total_latency;
    
    // Add to pending orders
    pending_orders_.push_back(order);
    
    std::cout << "[Engine] Order " << order.order_id << " submitted: "
              << (order.side == Side::BUY ? "BUY" : "SELL") << " "
              << order.size << " @ " 
              << (order.order_type == OrderType::MARKET ? "MARKET" : std::to_string(order.price))
              << " (active at t+" << total_latency << "ns)" << std::endl;
    
    return order.order_id;
}

bool MatchingEngine::cancel_order(uint64_t order_id) {
    auto it = std::find_if(pending_orders_.begin(), pending_orders_.end(),
        [order_id](const Order& o) { return o.order_id == order_id; });
    
    if (it != pending_orders_.end()) {
        it->status = OrderStatus::CANCELLED;
        pending_orders_.erase(it);
        return true;
    }
    return false;
}

std::vector<Fill> MatchingEngine::process_pending_orders(uint64_t current_timestamp) {
    /**
     * Section 6 - Process orders that are now active
     * 
     * For each pending order:
     * 1. Check if order is now active (latency elapsed)
     * 2. Check if order can be matched
     * 3. Apply slippage model (Section 8.3)
     * 4. Generate fill
     */
    
    std::vector<Fill> fills;
    std::vector<Order> remaining_orders;
    
    for (auto& order : pending_orders_) {
        // Check if order is active yet (Section 8.1 - Latency)
        if (current_timestamp < order.activation_time) {
            remaining_orders.push_back(order);
            continue;
        }
        
        // Order is now active
        order.status = OrderStatus::ACTIVE;
        
        // Get market state for this symbol
        auto state_it = market_states_.find(order.symbol_id);
        if (state_it == market_states_.end()) {
            remaining_orders.push_back(order);
            continue;
        }
        
        const MarketState& market = state_it->second;
        
        // Try to match order
        Fill fill;
        bool matched = false;
        
        if (order.order_type == OrderType::MARKET) {
            matched = match_market_order(order, market, fill);
        } else if (order.order_type == OrderType::LIMIT) {
            matched = match_limit_order(order, market, fill);
        } else if (order.order_type == OrderType::STOP) {
            matched = match_stop_order(order, market, fill);
        }
        
        if (matched) {
            // Apply slippage (Section 8.3)
            apply_slippage(fill, order, market);
            
            fill.timestamp = current_timestamp;
            fills.push_back(fill);
            order.status = OrderStatus::FILLED;
        } else {
            // Order not filled yet, keep it
            remaining_orders.push_back(order);
        }
    }
    
    pending_orders_ = std::move(remaining_orders);
    return fills;
}

bool MatchingEngine::match_market_order(const Order& order, const MarketState& market, Fill& fill) {
    /**
     * Section 6.1 - Market Order Matching
     * Market orders execute immediately at best available price
     */
    
    fill.order_id = order.order_id;
    fill.symbol_id = order.symbol_id;
    fill.side = order.side;
    fill.volume = order.size;
    
    if (order.side == Side::BUY) {
        // Buy at ask price
        fill.price = (market.ask > 0) ? market.ask : market.last_price;
    } else {
        // Sell at bid price
        fill.price = (market.bid > 0) ? market.bid : market.last_price;
    }
    
    return true;
}

bool MatchingEngine::match_limit_order(const Order& order, const MarketState& market, Fill& fill) {
    /**
     * Section 6.2 - Limit Order Matching
     * Limit orders execute only if price is favorable
     */
    
    bool can_fill = false;
    
    if (order.side == Side::BUY) {
        // Buy limit: execute if ask <= limit price
        if (market.ask > 0 && market.ask <= order.price) {
            fill.price = market.ask;
            can_fill = true;
        } else if (market.last_price <= order.price) {
            fill.price = market.last_price;
            can_fill = true;
        }
    } else {
        // Sell limit: execute if bid >= limit price
        if (market.bid > 0 && market.bid >= order.price) {
            fill.price = market.bid;
            can_fill = true;
        } else if (market.last_price >= order.price) {
            fill.price = market.last_price;
            can_fill = true;
        }
    }
    
    if (can_fill) {
        fill.order_id = order.order_id;
        fill.symbol_id = order.symbol_id;
        fill.side = order.side;
        fill.volume = order.size;
    }
    
    return can_fill;
}

bool MatchingEngine::match_stop_order(const Order& order, const MarketState& market, Fill& fill) {
    /**
     * Section 6 - Stop Order Matching
     * Stop orders become market orders when price crosses stop level
     */
    
    bool triggered = false;
    
    if (order.side == Side::BUY) {
        // Buy stop: trigger when price >= stop price
        triggered = market.last_price >= order.price;
    } else {
        // Sell stop: trigger when price <= stop price
        triggered = market.last_price <= order.price;
    }
    
    if (triggered) {
        // Convert to market order execution
        fill.order_id = order.order_id;
        fill.symbol_id = order.symbol_id;
        fill.side = order.side;
        fill.volume = order.size;
        fill.price = market.last_price;
        return true;
    }
    
    return false;
}

void MatchingEngine::apply_slippage(Fill& fill, const Order& order, const MarketState& market) {
    /**
     * Section 8.3 - Slippage Model
     * 
     * Slippage = fixed_bps + volatility_mult * σ + size_impact * (size/ADV)
     * Plus optional stochastic component
     */
    
    double slippage_bps = slippage_config_.fixed_bps;
    
    // Add volatility component (simplified - would need historical vol calculation)
    // slippage_bps += slippage_config_.volatility_mult * estimated_volatility;
    
    // Add size impact (simplified)
    // slippage_bps += slippage_config_.size_impact * (order.size / average_daily_volume);
    
    // Add stochastic component if enabled
    if (slippage_config_.use_stochastic && slippage_config_.stochastic_std > 0) {
        std::normal_distribution<double> dist(0.0, slippage_config_.stochastic_std);
        slippage_bps += dist(rng_);
    }
    
    // Ensure non-negative slippage
    slippage_bps = std::max(0.0, slippage_bps);
    
    // Apply slippage to fill price
    double slippage_mult = slippage_bps / 10000.0;  // Convert bps to decimal
    
    if (fill.side == Side::BUY) {
        // Buying: slippage increases price
        fill.price *= (1.0 + slippage_mult);
    } else {
        // Selling: slippage decreases price
        fill.price *= (1.0 - slippage_mult);
    }
    
    fill.slippage = slippage_bps;
}

double MatchingEngine::get_best_bid(uint32_t symbol_id) const {
    auto it = market_states_.find(symbol_id);
    return (it != market_states_.end()) ? it->second.bid : 0.0;
}

double MatchingEngine::get_best_ask(uint32_t symbol_id) const {
    auto it = market_states_.find(symbol_id);
    return (it != market_states_.end()) ? it->second.ask : 0.0;
}

double MatchingEngine::get_last_price(uint32_t symbol_id) const {
    auto it = market_states_.find(symbol_id);
    return (it != market_states_.end()) ? it->second.last_price : 0.0;
}

size_t MatchingEngine::pending_order_count() const {
    return pending_orders_.size();
}

const std::vector<Order>& MatchingEngine::get_pending_orders() const {
    return pending_orders_;
}

} // namespace felix