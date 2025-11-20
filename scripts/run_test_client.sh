#!/bin/bash
# Quick start script for heartbeat test client

echo "=== Starting Heartbeat Test Client ==="
echo "Setting protobuf compatibility..."
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

echo "Starting client..."
python test_heartbeat.py
