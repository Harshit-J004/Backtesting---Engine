#pragma once

#include "felix/execution.hpp"
#include <vector>
#include <unordered_map>

namespace felix {

/**
 * OrderBook - Section 6.2
 * Maintains bid/ask orders for queue simulation
 */
class OrderBook {
public:
    void add_order(const Order& order);
    void cancel_order(uint64_t order_id);
    std::vector<Fill> check_fills(double market_price);
    
    double best_bid() const;
    double best_ask() const;
    
    const std::vector<Order>& bids() const { return bids_; }
    const std::vector<Order>& asks() const { return asks_; }
    size_t size() const { return orders_.size(); }

private:
    std::unordered_map<uint64_t, Order> orders_;
    std::vector<Order> bids_;
    std::vector<Order> asks_;
};

} // namespace felix