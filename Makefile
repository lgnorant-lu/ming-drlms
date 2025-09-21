CC = gcc
CFLAGS = -Wall -Wextra -pthread -Werror -Wno-deprecated-declarations
LIBS_COMMON = -lrt
LIBS_SERVER = -lrt -lcrypto
LIBS_AGENT = -lcrypto

# install destinations
PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib
INCLUDEDIR ?= $(PREFIX)/include
PKGCONFIGDIR ?= $(LIBDIR)/pkgconfig

SRC_LIBIPC = src/libipc/shared_buffer.c
SRC_SERVER = src/server/log_collector_server.c src/server/rooms.c
SRC_AGENT = src/agent/log_agent.c
SRC_TOOLS = src/tools/proc_launcher.c src/tools/log_consumer.c

all: libipc.a libipc.so log_collector_server log_agent proc_launcher log_consumer ipc_sender

%.o: %.c
	$(CC) $(CFLAGS) -fPIC -c $< -o $@

libipc.a: $(SRC_LIBIPC:.c=.o)
	ar rcs $@ $^

libipc.so: $(SRC_LIBIPC:.c=.o)
	$(CC) $(CFLAGS) -shared -o $@ $^ $(LIBS_COMMON)

log_collector_server: $(SRC_SERVER) libipc.a
	$(CC) $(CFLAGS) -o $@ $(SRC_SERVER) -L. -lipc $(LIBS_SERVER) -Wl,-rpath,'$$ORIGIN'

log_agent: $(SRC_AGENT)
	$(CC) $(CFLAGS) -o $@ $< $(LIBS_AGENT) -Wl,-rpath,'$$ORIGIN'

proc_launcher: $(SRC_TOOLS)
	$(CC) $(CFLAGS) -o $@ src/tools/proc_launcher.c -Wl,-rpath,'$$ORIGIN'

log_consumer: src/tools/log_consumer.c libipc.a
	$(CC) $(CFLAGS) -o $@ $< -L. -lipc $(LIBS_COMMON) -Wl,-rpath,'$$ORIGIN'

ipc_sender: src/tools/ipc_sender.c libipc.a
	$(CC) $(CFLAGS) -o $@ $< -L. -lipc $(LIBS_COMMON) -Wl,-rpath,'$$ORIGIN'

debug:
	$(MAKE) CFLAGS="$(CFLAGS) -g -O0 -DDEBUG" all

clean:
	find . -type f \( -name "*.o" -o -name "*.a" -o -name "*.so" -o -name "*.gcno" -o -name "*.gcda" -o -name "*.gcov" \) -delete || true
	rm -f log_collector_server log_agent proc_launcher log_consumer ipc_sender || true

.PHONY: all debug clean

# Tests & Coverage
TESTS = tests/test_ipc

tests/test_ipc: tests/test_ipc.c libipc.a
	$(CC) $(CFLAGS) -o $@ $< -L. -lipc $(LIBS_COMMON) -Wl,-rpath,'$$ORIGIN'

test: $(TESTS) log_agent log_collector_server ipc_sender log_consumer
	@echo "Starting server..."
	-pkill -f log_collector_server >/dev/null 2>&1 || true
	# use a fresh data dir to avoid EXISTS errors
	rm -rf /tmp/drlms_test_data && mkdir -p /tmp/drlms_test_data
	LD_LIBRARY_PATH=. DRLMS_DATA_DIR=/tmp/drlms_test_data DRLMS_AUTH_STRICT=0 ./log_collector_server >/tmp/drlms_test_server.log 2>&1 & echo $$! > /tmp/drlms_test.pid
	# wait for port 8080 up to ~5s
	set +e; for i in 1 2 3 4 5 6 7 8; do (exec 3<>/dev/tcp/127.0.0.1/8080) >/dev/null 2>&1 && break || sleep 0.6; done; set -e
	@echo "Running unit tests..." && DRLMS_SHM_KEY=0x4c4f4754 LD_LIBRARY_PATH=. ./tests/test_ipc | sed -n '1,10p'
	@echo "Running protocol integration..." && chmod +x tests/integration_protocol.sh && HOST=127.0.0.1 PORT=8080 bash -lc 'LD_LIBRARY_PATH=. ./tests/integration_protocol.sh $${HOST} $${PORT} README.md /tmp/README.md'
	@echo "Running space integration..." && chmod +x tests/integration_space.sh && export PATH=$$HOME/.local/bin:$$PATH; HOST=127.0.0.1 PORT=8080 bash -lc 'LD_LIBRARY_PATH=. ./tests/integration_space.sh $${HOST} $${PORT} demo'
	@echo "Stopping server..."
	-kill -TERM $$(cat /tmp/drlms_test.pid) >/dev/null 2>&1 || true
	-rm -f /tmp/drlms_test.pid

# install/uninstall
install: all
	install -d $(DESTDIR)$(BINDIR) $(DESTDIR)$(LIBDIR) $(DESTDIR)$(INCLUDEDIR) $(DESTDIR)$(PKGCONFIGDIR)
	install -m 755 log_collector_server log_agent proc_launcher log_consumer ipc_sender $(DESTDIR)$(BINDIR)
	install -m 644 libipc.a $(DESTDIR)$(LIBDIR)
	install -m 755 libipc.so $(DESTDIR)$(LIBDIR)
	install -m 644 src/libipc/shared_buffer.h $(DESTDIR)$(INCLUDEDIR)/shared_buffer.h
	@echo "prefix=$(PREFIX)" > libipc.pc
	@echo "exec_prefix=$${prefix}" >> libipc.pc
	@echo "libdir=$(LIBDIR)" >> libipc.pc
	@echo "includedir=$(INCLUDEDIR)" >> libipc.pc
	@echo "" >> libipc.pc
	@echo "Name: libipc" >> libipc.pc
	@echo "Description: DRLMS shared memory IPC library" >> libipc.pc
	@echo "Version: 1.0.0" >> libipc.pc
	@echo "Libs: -L$${libdir} -lipc -lrt -lpthread" >> libipc.pc
	@echo "Cflags: -I$${includedir}" >> libipc.pc
	install -m 644 libipc.pc $(DESTDIR)$(PKGCONFIGDIR)/libipc.pc
	@rm -f libipc.pc


uninstall:
	rm -f $(DESTDIR)$(BINDIR)/log_collector_server $(DESTDIR)$(BINDIR)/log_agent $(DESTDIR)$(BINDIR)/proc_launcher $(DESTDIR)$(BINDIR)/log_consumer || true
	rm -f $(DESTDIR)$(BINDIR)/ipc_sender || true
	rm -f $(DESTDIR)$(LIBDIR)/libipc.a $(DESTDIR)$(LIBDIR)/libipc.so || true
	rm -f $(DESTDIR)$(INCLUDEDIR)/shared_buffer.h || true
	rm -f $(DESTDIR)$(PKGCONFIGDIR)/libipc.pc || true

# source distribution
dist:
	mkdir -p dist
	tar --exclude='dist' --exclude='*.o' --exclude='*.so' --exclude='*.a' \
	    --exclude='*.gcda' --exclude='*.gcno' --exclude='*.gcov' \
	    --exclude='server_files/*.log' -czf dist/drlms.tar.gz \
	    Makefile README.md lgn/Requirments.md clean.sh start_all.sh \
	    src tests server_files lgn/Oringinnal_requirements.md lgn/Report_requirements.md

# IPC coverage (focus on libipc with local producer/consumer)
.PHONY: coverage_ipc
coverage_ipc:
	$(MAKE) clean
	# build only ipc-related targets with coverage
	$(MAKE) CFLAGS="$(CFLAGS) --coverage" libipc.a log_consumer ipc_sender tests/test_ipc
	DRLMS_SHM_KEY=0x4c4f4755 LD_LIBRARY_PATH=. ./tests/test_ipc >/dev/null || true
	# simple local producer/consumer exercise
	( LD_LIBRARY_PATH=. DRLMS_SHM_KEY=0x4c4f4755 ./log_consumer & echo $$! > /tmp/drlms_ipc.pid ); sleep 0.2; \
	 echo "hello-ipc" | DRLMS_SHM_KEY=0x4c4f4755 ./ipc_sender; \
	 kill -TERM $$(cat /tmp/drlms_ipc.pid) 2>/dev/null || true; rm -f /tmp/drlms_ipc.pid
	mkdir -p coverage
	gcov -o src/libipc src/libipc/shared_buffer.c > coverage/gcov_ipc.txt 2>&1 || true

coverage:
	$(MAKE) clean
	$(MAKE) CFLAGS="$(CFLAGS) --coverage" all
	-pkill -f log_collector_server || true
	LD_LIBRARY_PATH=. DRLMS_DATA_DIR=server_files DRLMS_SHM_KEY=0x4c4f4742 ./log_collector_server >/tmp/drlms_server.log 2>&1 & echo $$! > /tmp/drlms_cov.pid
	sleep 0.8
	# run minimal integration to avoid long negatives interfering
	LD_LIBRARY_PATH=. HOST=127.0.0.1 PORT=8080 COVERAGE_MIN=1 bash -lc './tests/integration_protocol.sh $$HOST $$PORT README.md /tmp/README.md' || true
	# minimal space flow
	LD_LIBRARY_PATH=. HOST=127.0.0.1 PORT=8080 bash -lc './tests/integration_space.sh $$HOST $$PORT demo' || true
	# run ipc unit test to generate gcda for libipc
	DRLMS_SHM_KEY=0x4c4f4754 LD_LIBRARY_PATH=. ./tests/test_ipc | sed -n '1,6p' || true
	sleep 0.2
	-kill -TERM $$(cat /tmp/drlms_cov.pid) 2>/dev/null || true
	-rm -f /tmp/drlms_cov.pid
	mkdir -p coverage
	gcov -o src/libipc src/libipc/shared_buffer.c > coverage/gcov.txt 2>&1 || true
	gcov -o . src/server/log_collector_server.c src/agent/log_agent.c >> coverage/gcov.txt 2>&1 || true
	@echo "Coverage written to coverage/gcov.txt"

# CLI helpers
.PHONY: cli-install cli-uninstall
cli-install:
	python3 -m pip install --user pipx || true
	python3 -m pipx ensurepath || true
	python3 -m pipx install tools/cli || python3 -m pipx reinstall ming-drlms

cli-uninstall:
	python3 -m pipx uninstall ming-drlms || true


