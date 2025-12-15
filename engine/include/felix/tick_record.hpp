#pragma once
#include <cstdint>

namespace felix {

#pragma pack(push, 1)
struct TickRecord {
    uint64_t timestamp;     // 8 bytes
    uint32_t symbol_id;     // 4 bytes
    float price;            // 4 bytes
    float bid;              // 4 bytes
    float ask;              // 4 bytes
    float bid_size;         // 4 bytes
    float ask_size;         // 4 bytes
    uint32_t volume;        // 4 bytes
    uint32_t padding;       // 4 bytes
};
#pragma pack(pop)

static_assert(sizeof(TickRecord) == 40, "TickRecord must be 40 bytes");

} // namespace felix