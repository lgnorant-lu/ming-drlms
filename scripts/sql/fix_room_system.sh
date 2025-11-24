#!/bin/bash
set -e
pkill -f log_collector_server || true
python3 migrate_db.py drlms.db
rm -rf build && mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release && cmake --build . -j$(nproc)
cd .. && python3 test_room_ownership.py drlms.db
export DRLMS_DATA_DIR=$PWD && export DRLMS_PORT=15035
nohup ./build/log_collector_server > server.log 2>&1 &
echo "✅ 完成！查看日志: tail -f server.log"
