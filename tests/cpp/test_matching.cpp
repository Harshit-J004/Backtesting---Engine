#include "felix/matching.hpp"
#include <iostream>
#include <cassert>

using namespace felix;

int main() {
    // Create matching engine with slippage
    SlippageConfig slippage;
    slippage.fixed_bps = 5.0;
    MatchingEngine engine(slippage);
    
    // Configure latency
    LatencyConfig latency;
    latency.strategy_latency_ns = 1000;
    latency.engine_latency_ns = 500;
    engine.set_latency_config(latency);
    
    // Create a market tick
    TickRecord tick;
    tick.timestamp = 1000000000ULL;
    tick.symbol_id = 1;
    tick.price = 100.0;
    tick.bid = 99.99;
    tick.ask = 100.01;
    tick.bid_size = 100;
    tick.ask_size = 100;
    tick.volume = 1000;
    
    // Update market state
    engine.update_market_state(tick);
    
    // Submit a market buy order
    Order order;
    order.symbol_id = 1;
    order.side = Side::BUY;
    order.order_type = OrderType::MARKET;
    order.size = 10;
    order.timestamp = tick.timestamp;
    
    uint64_t order_id = engine.submit_order(order);
    assert(order_id > 0);
    assert(engine.pending_order_count() == 1);
    
    // Process orders (latency not elapsed yet)
    std::vector<Fill> fills = engine.process_pending_orders(tick.timestamp);
    assert(fills.empty());  // Order not yet active due to latency
    
    // Advance time past latency
    uint64_t later_time = tick.timestamp + latency.strategy_latency_ns + latency.engine_latency_ns + 1;
    fills = engine.process_pending_orders(later_time);
    
    assert(fills.size() == 1);
    assert(fills[0].order_id == order_id);
    assert(fills[0].side == Side::BUY);
    assert(fills[0].volume == 10);
    assert(fills[0].slippage > 0);  // Slippage applied
    
    std::cout << "Fill price: " << fills[0].price << " (with " << fills[0].slippage << " bps slippage)" << std::endl;
    
    std::cout << "All MatchingEngine tests passed!" << std::endl;
    return 0;
}