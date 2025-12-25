cmake_minimum_required(VERSION 3.15)
project(felix_backtester VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(Python_FIND_VIRTUALENV ONLY) 

if(MSVC)
    add_compile_options(/O2 /Oi /Ot /Oy /GL)
else()
    add_compile_options(-O3 -march=native -flto)
endif()

find_package(Python 3.13 COMPONENTS Interpreter Development REQUIRED)

execute_process(
    COMMAND "${Python_EXECUTABLE}" -m pybind11 --cmakedir
    OUTPUT_VARIABLE pybind11_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
)

find_package(pybind11 REQUIRED)

include_directories(engine/include)

set(ENGINE_SOURCES
    engine/src/core/datastream.cpp
    engine/src/core/event_loop.cpp
    engine/src/core/portfolio.cpp
    engine/src/matching/order_book.cpp
    engine/src/matching/matching.cpp
    engine/src/risk/risk_engine.cpp
    engine/src/data/tick_record.cpp
)

pybind11_add_module(felix_engine MODULE
    engine/src/bindings/pybind_module.cpp
    ${ENGINE_SOURCES}
)

set_target_properties(felix_engine PROPERTIES LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}")


target_link_libraries(felix_engine PRIVATE pybind11::module)




