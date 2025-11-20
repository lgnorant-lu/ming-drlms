#!/bin/bash
# Quick start script for DRLMS server

echo "=== Starting DRLMS Server ==="
echo "Killing existing server..."
pkill -f log_collector_server
sleep 1

echo "Setting environment..."
export DRLMS_DATA_DIR=$PWD
export DRLMS_PORT=15035

echo "Starting server on port 15035..."
./build/log_collector_server
