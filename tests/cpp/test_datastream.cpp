#include "felix/datastream.hpp"
#include <iostream>
#include <fstream>
#include <cassert>

using namespace felix;

int main() {
    // Create test data file
    std::string test_file = "/tmp/test_ticks.bin";
    
    {
        std::vector<TickRecord> ticks(100);
        for (int i = 0; i < 100; i++) {
            ticks[i].timestamp = 1000000000ULL + i * 1000000ULL;
            ticks[i].symbol_id = 1;
            ticks[i].price = 100.0 + i * 0.1;
            ticks[i].bid = ticks[i].price - 0.01;
            ticks[i].ask = ticks[i].price + 0.01;
            ticks[i].bid_size = 100;
            ticks[i].ask_size = 100;
            ticks[i].volume = 1000;
        }
        
        std::ofstream file(test_file, std::ios::binary);
        file.write(reinterpret_cast<const char*>(ticks.data()), 
                   ticks.size() * sizeof(TickRecord));
    }
    
    // Test loading
    DataStream stream;
    assert(stream.load(test_file));
    assert(stream.size() == 100);
    
    // Test iteration
    int count = 0;
    while (stream.has_next()) {
        const TickRecord& tick = stream.next();
        count++;
    }
    assert(count == 100);
    
    // Test reset
    stream.reset();
    assert(stream.has_next());
    assert(stream.current_index() == 0);
    
    std::cout << "All DataStream tests passed!" << std::endl;
    return 0;
}