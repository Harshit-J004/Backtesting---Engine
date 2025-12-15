#include "felix/order_book.hpp"
#include <algorithm>

namespace felix {

void OrderBook::add_order(const Order& order) {
    orders_[order.order_id] = order;
    
    if (order.side == Side::BUY) {
        bids_.push_back(order);
        std::sort(bids_.begin(), bids_.end(), [](const Order& a, const Order& b) {
            return a.price > b.price;  // Higher price first for bids
        });
    } else {
        asks_.push_back(order);
        std::sort(asks_.begin(), asks_.end(), [](const Order& a, const Order& b) {
            return a.price < b.price;  // Lower price first for asks
        });
    }
}

void OrderBook::cancel_order(uint64_t order_id) {
    auto it = orders_.find(order_id);
    if (it != orders_.end()) {
        it->second.status = OrderStatus::CANCELLED;
        
        // Remove from bids/asks
        bids_.erase(std::remove_if(bids_.begin(), bids_.end(), 
            [order_id](const Order& o) { return o.order_id == order_id; }), bids_.end());
        asks_.erase(std::remove_if(asks_.begin(), asks_.end(), 
            [order_id](const Order& o) { return o.order_id == order_id; }), asks_.end());
        
        orders_.erase(it);
    }
}

std::vector<Fill> OrderBook::check_fills(double market_price) {
    std::vector<Fill> fills;
    
    // Check bids that can be filled (market price <= bid price)
    for (auto it = bids_.begin(); it != bids_.end();) {
        const Order& order = *it;
        if (order.status == OrderStatus::ACTIVE && market_price <= order.price) {
            Fill fill;
            fill.order_id = order.order_id;
            fill.symbol_id = order.symbol_id;
            fill.side = order.side;
            fill.price = order.price;
            fill.volume = order.size;
            fill.timestamp = 0;  // Will be set by caller
            fill.slippage = 0.0;
            fills.push_back(fill);
            
            orders_.erase(order.order_id);
            it = bids_.erase(it);
        } else {
            ++it;
        }
    }
    
    // Check asks that can be filled (market price >= ask price)
    for (auto it = asks_.begin(); it != asks_.end();) {
        const Order& order = *it;
        if (order.status == OrderStatus::ACTIVE && market_price >= order.price) {
            Fill fill;
            fill.order_id = order.order_id;
            fill.symbol_id = order.symbol_id;
            fill.side = order.side;
            fill.price = order.price;
            fill.volume = order.size;
            fill.timestamp = 0;
            fill.slippage = 0.0;
            fills.push_back(fill);
            
            orders_.erase(order.order_id);
            it = asks_.erase(it);
        } else {
            ++it;
        }
    }
    
    return fills;
}

double OrderBook::best_bid() const {
    return bids_.empty() ? 0.0 : bids_.front().price;
}

double OrderBook::best_ask() const {
    return asks_.empty() ? 0.0 : asks_.front().price;
}

} // namespace felix