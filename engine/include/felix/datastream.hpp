#pragma once

#include "felix/tick_record.hpp"
#include <vector>
#include <string>

namespace felix {

/**
 * DataStream - Section 4.1
 * Memory-mapped binary tick data access
 */
class DataStream {
public:
    DataStream();
    ~DataStream();
    
    // Load binary tick data
    bool load(const std::string& filepath);
    
    // Stream interface
    size_t size() const;
    bool has_next() const;
    const TickRecord& next();
    const TickRecord& peek() const;
    void reset();
    
    // Current position
    size_t current_index() const { return current_index_; }

private:
    std::vector<TickRecord> ticks_;
    size_t current_index_;
};

} // namespace felix