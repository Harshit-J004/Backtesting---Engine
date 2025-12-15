#pragma once

#include <cstdint>

namespace felix {

/**
 * Order Side
 */
enum class Side {
    BUY,
    SELL
};

/**
 * Order Type - Section 6.1
 */
enum class OrderType {
    MARKET,
    LIMIT,
    STOP,
    STOP_LIMIT
};

/**
 * Order Status
 */
enum class OrderStatus {
    PENDING,    // Submitted but not yet active (latency pending)
    ACTIVE,     // Active and eligible for matching
    PARTIAL,    // Partially filled
    FILLED,     // Completely filled
    CANCELLED,  // Cancelled by user
    REJECTED    // Rejected by risk engine
};

/**
 * Order - Section 6.1
 */
struct Order {
    uint64_t order_id = 0;
    uint32_t symbol_id = 0;
    Side side = Side::BUY;
    OrderType order_type = OrderType::MARKET;
    double price = 0.0;
    double size = 0.0;
    uint64_t timestamp = 0;
    uint64_t activation_time = 0;  // When order becomes active (after latency)
    OrderStatus status = OrderStatus::PENDING;
    double queue_position = 0.0;   // For queue modeling (Section 6.2)
};

/**
 * Fill - Section 6.3
 */
struct Fill {
    uint64_t order_id = 0;
    uint32_t symbol_id = 0;
    Side side = Side::BUY;
    double price = 0.0;
    double volume = 0.0;
    uint64_t timestamp = 0;
    double slippage = 0.0;  // Slippage in basis points
};

} // namespace felix