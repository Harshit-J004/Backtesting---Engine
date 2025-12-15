#include "felix/datastream.hpp"
#include <fstream>
#include <iostream>
#include <cstring>

namespace felix {

DataStream::DataStream() : current_index_(0) {}

DataStream::~DataStream() = default;

bool DataStream::load(const std::string& filepath) {
    std::ifstream file(filepath, std::ios::binary);
    if (!file.is_open()) {
        std::cerr << "[DataStream] Failed to open: " << filepath << std::endl;
        return false;
    }
    
    // Get file size
    file.seekg(0, std::ios::end);
    size_t file_size = file.tellg();
    file.seekg(0, std::ios::beg);
    
    // Calculate number of ticks
    size_t tick_size = sizeof(TickRecord);
    size_t num_ticks = file_size / tick_size;
    
    std::cout << "[DataStream] File size: " << file_size << " bytes" << std::endl;
    std::cout << "[DataStream] TickRecord size: " << tick_size << " bytes" << std::endl;
    std::cout << "[DataStream] Expected ticks: " << num_ticks << std::endl;
    
    if (file_size % tick_size != 0) {
        std::cerr << "[DataStream] WARNING: File size not evenly divisible by tick size!" << std::endl;
        std::cerr << "[DataStream] Remainder: " << (file_size % tick_size) << " bytes" << std::endl;
    }
    
    if (num_ticks == 0) {
        std::cerr << "[DataStream] No ticks in file" << std::endl;
        return false;
    }
    
    // Read all ticks
    ticks_.resize(num_ticks);
    file.read(reinterpret_cast<char*>(ticks_.data()), num_ticks * tick_size);
    
    current_index_ = 0;
    
    std::cout << "[DataStream] Loaded " << num_ticks << " ticks from " << filepath << std::endl;
    
    // Debug: Print first tick
    if (!ticks_.empty()) {
        const auto& t = ticks_[0];
        std::cout << "[DataStream] First tick: ts=" << t.timestamp 
                  << " symbol=" << t.symbol_id
                  << " price=" << t.price 
                  << " bid=" << t.bid
                  << " ask=" << t.ask
                  << " vol=" << t.volume << std::endl;
    }
    
    return true;
}

size_t DataStream::size() const {
    return ticks_.size();
}

bool DataStream::has_next() const {
    return current_index_ < ticks_.size();
}

const TickRecord& DataStream::next() {
    return ticks_[current_index_++];
}

const TickRecord& DataStream::peek() const {
    return ticks_[current_index_];
}

void DataStream::reset() {
    current_index_ = 0;
}

} // namespace felix