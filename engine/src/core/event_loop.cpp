#include "felix/event_loop.hpp"
#include <iostream>
#include <algorithm>

namespace felix {

EventLoop::EventLoop() 
    : matching_engine_(nullptr)
    , portfolio_(nullptr)
    , risk_engine_(nullptr)
    , ticks_processed_(0)
    , orders_processed_(0)
    , fills_generated_(0)
    , peak_equity_(0.0)
    , risk_halted_(false) {}

EventLoop::~EventLoop() = default;

void EventLoop::set_matching_engine(MatchingEngine* engine) {
    matching_engine_ = engine;
}

void EventLoop::set_portfolio(Portfolio* portfolio) {
    portfolio_ = portfolio;
    if (portfolio_) {
        peak_equity_ = portfolio_->equity();
    }
}

void EventLoop::set_risk_engine(RiskEngine* risk_engine) {
    risk_engine_ = risk_engine;
}

void EventLoop::run(DataStream& stream, StrategyWrapper& strategy) {
    /**
     * Section 5.2 - Core Event Loop
     * 
     * Deterministic: single thread, fixed random seed, strict timestamp order.
     * Risk before strategy: internal exits happen even if Python is slow.
     */
    
    if (!matching_engine_ || !portfolio_) {
        std::cerr << "[EventLoop] ERROR: MatchingEngine or Portfolio not set!" << std::endl;
        return;
    }

    // Initialize peak equity for drawdown tracking
    peak_equity_ = portfolio_->equity();
    
    // Call strategy start
    strategy.on_start();
    
    std::cout << "[EventLoop] Starting backtest with " << stream.size() << " ticks" << std::endl;

    // Main event loop - Section 5.2
    while (stream.has_next()) {
        const TickRecord& tick = stream.next();
        process_tick(tick, strategy);
        ticks_processed_++;
        
        // Progress logging every 100k ticks
        if (ticks_processed_ % 100000 == 0) {
            std::cout << "[EventLoop] Processed " << ticks_processed_ << " ticks, "
                      << "Equity: $" << portfolio_->equity() << std::endl;
        }
    }

    // Final processing
    strategy.on_end();
    
    std::cout << "[EventLoop] Backtest complete. Processed " << ticks_processed_ 
              << " ticks, " << orders_processed_ << " orders, " 
              << fills_generated_ << " fills" << std::endl;
}

void EventLoop::process_tick(const TickRecord& tick, StrategyWrapper& strategy) {
    /**
     * Section 5.2 - Per-tick processing:
     * 1. Update market state in matching engine
     * 2. Process any pending orders that can now be filled
     * 3. Notify strategy of fills
     * 4. Update portfolio mark-to-market
     * 5. Check risk limits
     * 6. Wake strategy if appropriate
     */
    
    // Step 1: Update market state - Section 6
    matching_engine_->update_market_state(tick);
    
    // Step 2: Check and execute pending orders - Section 6.1
    // Step 3: Notify strategy of fills
    check_pending_orders(tick, strategy);
    
    // Step 4: Update portfolio mark-to-market - Section 4.2
    update_portfolio_mtm(tick);
    
    // Step 5: Check risk limits - Section 8.4
    check_risk_limits(strategy);
    
    // Step 6: Wake strategy (if not halted)
    if (!risk_halted_ && !strategy.is_halted()) {
        if (strategy.should_wake(tick)) {
            strategy.on_tick(tick);
        }
    }
}

void EventLoop::check_pending_orders(const TickRecord& tick, StrategyWrapper& strategy) {
    /**
     * Section 6.1-6.2 - Order Processing
     * Process pending orders against current market state
     * Applies latency model (Section 8.1) and slippage (Section 8.3)
     * Notifies strategy via on_fill callback (Section 7)
     */
    
    if (!matching_engine_ || !portfolio_) return;
    
    // Get fills from matching engine
    std::vector<Fill> fills = matching_engine_->process_pending_orders(tick.timestamp);
    
    for (const Fill& fill : fills) {
        // Update portfolio with fill
        portfolio_->on_fill(fill);
        fills_generated_++;
        orders_processed_++;
        
        // Log fill
        std::cout << "[Fill] Order " << fill.order_id 
                  << " " << (fill.side == Side::BUY ? "BUY" : "SELL")
                  << " " << fill.volume << " @ $" << fill.price
                  << " (slippage: " << fill.slippage << " bps)" << std::endl;
        
        // CRITICAL: Notify strategy of fill - Section 7
        strategy.on_fill(fill);
    }
}

void EventLoop::update_portfolio_mtm(const TickRecord& tick) {
    /**
     * Section 4.2 & 8.4 - Mark-to-Market
     * Update portfolio prices and record equity point
     */
    
    if (!portfolio_) return;
    
    // Update price for this symbol
    portfolio_->update_prices(tick.symbol_id, tick.price);
    
    // Append equity point to curve
    portfolio_->append_equity_point(tick.timestamp);
    
    // Update peak equity for drawdown calculation
    double current_equity = portfolio_->equity();
    if (current_equity > peak_equity_) {
        peak_equity_ = current_equity;
    }
}

void EventLoop::check_risk_limits(StrategyWrapper& strategy) {
    /**
     * Section 8.4 - Risk Management
     * Check drawdown limits and halt if exceeded
     */
    
    if (!risk_engine_ || !portfolio_) return;
    
    // Check drawdown limit
    if (!risk_engine_->check_drawdown(*portfolio_, peak_equity_)) {
        if (!risk_halted_) {
            std::cout << "[RISK] Max drawdown exceeded! Halting strategy." << std::endl;
            risk_halted_ = true;
            strategy.set_halted(true);
            risk_engine_->halt();
        }
    }
}

} // namespace felix