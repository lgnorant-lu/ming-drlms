CC = gcc
CFLAGS = -Wall -Wextra -pthread -Werror -Wno-deprecated-declarations
LIBS_COMMON = -lrt
LIBS_SERVER = -lrt -lcrypto -largon2
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
SRC_TOOLS = src/tools/proc_launcher.c src/tools/log_consumer.c src/tools/ipc_sender.c

# All C source files for coverage analysis
C_SOURCES = $(SRC_LIBIPC) $(SRC_SERVER) $(SRC_AGENT) $(SRC_TOOLS)

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
	$(CC) $(CFLAGS) -o $@ $(SRC_AGENT) $(LIBS_AGENT) -Wl,-rpath,'$$ORIGIN'

proc_launcher: src/tools/proc_launcher.c
	$(CC) $(CFLAGS) -o $@ src/tools/proc_launcher.c -Wl,-rpath,'$$ORIGIN'

log_consumer: src/tools/log_consumer.c libipc.a
	$(CC) $(CFLAGS) -o $@ $< -L. -lipc $(LIBS_COMMON) -Wl,-rpath,'$$ORIGIN'

ipc_sender: src/tools/ipc_sender.c libipc.a
	$(CC) $(CFLAGS) -o $@ $< -L. -lipc $(LIBS_COMMON) -Wl,-rpath,'$$ORIGIN'

debug:
	$(MAKE) CFLAGS="$(CFLAGS) -g -O0 -DDEBUG" all

clean:
	find . -type f \( -name "*.o" -o -name "*.a" -o -name "*.so" -o -name "*.gcno" -o -name "*.gcda" -o -name "*.gcov" \) -delete || true
	rm -f log_collector_server log_agent proc_launcher log_consumer ipc_sender tests/test_ipc_suite || true
	rm -rf coverage .coverage

.PHONY: all debug clean test coverage

# Tests & Coverage
TESTS = tests/test_ipc_suite

tests/test_ipc_suite: tests/test_ipc_suite.c libipc.a
	$(CC) $(CFLAGS) -Isrc/libipc -o $@ $< -L. -lipc $(LIBS_COMMON) -lcrypto -Wl,-rpath,'$$ORIGIN'

test: $(TESTS) log_agent log_collector_server ipc_sender log_consumer
	@echo "Starting server..."
	-pkill -f log_collector_server >/dev/null 2>&1 || true
	rm -rf /tmp/drlms_test_data && mkdir -p /tmp/drlms_test_data
	LD_LIBRARY_PATH=. DRLMS_DATA_DIR=/tmp/drlms_test_data DRLMS_AUTH_STRICT=0 ./log_collector_server >/tmp/drlms_test_server.log 2>&1 & echo $$! > /tmp/drlms_test.pid
	@set +e; for i in 1 2 3 4 5 6 7 8; do (exec 3<>/dev/tcp/127.0.0.1/8080) >/dev/null 2>&1 && break || sleep 0.6; done; set -e
	@echo "Running C unit tests..."
	DRLMS_SHM_KEY=0x4c4f4754 LD_LIBRARY_PATH=. ./tests/test_ipc_suite
	@echo "Running C protocol integration tests..."
	chmod +x tests/test_server_protocol.sh && HOST=127.0.0.1 PORT=8080 bash -lc 'LD_LIBRARY_PATH=. ./tests/test_server_protocol.sh $${HOST} $${PORT} README.md /tmp/README.md'
	@echo "Running Python E2E tests..."
	chmod +x tests/test_cli_e2e.sh && HOST=127.0.0.1 PORT=8080 bash -lc './tests/test_cli_e2e.sh'
	@echo "Stopping server..."
	-kill -TERM $$(cat /tmp/drlms_test.pid) >/dev/null 2>&1 || true
	-rm -f /tmp/drlms_test.pid

coverage:
	@echo "--- Generating comprehensive C and Python coverage report ---"
	$(MAKE) clean
	# 1. Build all C code with coverage flags
	@echo "--> Building C code with coverage instrumentation..."
	$(MAKE) CFLAGS="$(CFLAGS) --coverage" all tests/test_ipc_suite
	# 2. Run all tests to generate coverage data (delay creating ./coverage to avoid Python module shadowing)
	@echo "--> Running C unit tests (test_ipc_suite.c)..."
	DRLMS_SHM_KEY=0x4c4f4754 LD_LIBRARY_PATH=. ./tests/test_ipc_suite
	@echo "--> Running C protocol integration tests (test_server_protocol.sh)..."
	chmod +x tests/test_server_protocol.sh && HOST=127.0.0.1 PORT=8080 bash -lc 'LD_LIBRARY_PATH=. ./tests/test_server_protocol.sh $${HOST} $${PORT} README.md /tmp/README.md'
	@echo "--> Running C tools smoke tests (src/tools) ..."
	# proc_launcher: expect usage error (no args) and quick exit
	-./proc_launcher 2>/dev/null || true
	# ipc_sender/log_consumer: minimal local SHM loop to produce gcda quickly
	# send one short message via stdin, consumer reads 1 message and exits
	-( ./log_consumer --max 1 & echo $$! > .tmp_consumer.pid ); sleep 0.1; echo "hi" | ./ipc_sender >/dev/null 2>&1 || true; \
	  ( kill -TERM $$(cat .tmp_consumer.pid) 2>/dev/null || true; rm -f .tmp_consumer.pid )
	# proc_launcher success path (spawn /bin/echo)
	-./proc_launcher /bin/echo ok >/dev/null 2>&1 || true
	# ipc_sender message and file modes with a consumer reading 2 msgs
	echo "file-data" > /tmp/ipc_file.txt; \
	( ./log_consumer --max 2 >/dev/null 2>&1 & echo $$! > .tmp_consumer2.pid ); \
	sleep 0.1; \
	./ipc_sender --message "m1" >/dev/null 2>&1 || true; \
	./ipc_sender --file /tmp/ipc_file.txt >/dev/null 2>&1 || true; \
	( kill -TERM $$(cat .tmp_consumer2.pid) 2>/dev/null || true; rm -f .tmp_consumer2.pid /tmp/ipc_file.txt )
	@echo "--> Running Python E2E tests with coverage (test_cli_e2e.sh)..."
	@echo "--> Installing package in editable mode to generate _version.py..."
	@python3 -m pip install -e .
	rm -f .coverage
	chmod +x tests/test_cli_e2e.sh
	# Ensure python coverage is available
	python3 -c "import coverage" >/dev/null 2>&1 || python3 -m pip install --user -q coverage
	HOST=127.0.0.1 PORT=8080 PYTHONPATH=src CLI_COMMAND="python3 -m coverage run --branch --source=src/ming_drlms -a -m ming_drlms.main" ./tests/test_cli_e2e.sh
	# Run pytest-based CLI tests and append to Python coverage database
	python3 -c "import pytest" >/dev/null 2>&1 || python3 -m pip install --user -q pytest pytest-cov
	PYTHONPATH=src python3 -m coverage run --branch -a -m pytest -q tests/python || true
	# 3. Generate C coverage report
	@echo "--> Generating C coverage report with lcov (with branch coverage)..."
	@if command -v lcov >/dev/null 2>&1 && command -v genhtml >/dev/null 2>&1; then \
	  mkdir -p coverage coverage/html/c; \
	  lcov --quiet --rc lcov_branch_coverage=1 --capture --directory . --output-file coverage/c_coverage.info --no-external; \
	  # keep tests filtered but include src/tools in final report \
	  lcov --quiet --rc lcov_branch_coverage=1 --remove coverage/c_coverage.info '*/tests/*' --output-file coverage/c_coverage.filtered.info; \
	  genhtml --quiet --branch-coverage coverage/c_coverage.filtered.info --output-directory coverage/html/c; \
	else \
	  echo "[warn] lcov/genhtml not found; skipping C coverage report"; \
	fi
	# 4. Generate Python coverage report
	@echo "--> Generating Python coverage report..."
	mkdir -p coverage/html/python
	# Run coverage reporting in a temp directory to avoid module shadowing by ./coverage
	tmpdir=$$(mktemp -d); \
	( cd $$tmpdir && COVERAGE_FILE="$(shell pwd)/.coverage" python3 -m coverage report --include '*/src/ming_drlms/*' )
	tmpdir=$$(mktemp -d); \
	( cd $$tmpdir && COVERAGE_FILE="$(shell pwd)/.coverage" python3 -m coverage html --include '*/src/ming_drlms/*' -d "$(shell pwd)/coverage/html/python" )
	@echo "---"
	@echo "Coverage reports generated successfully:"
	@echo "C Report:       file://$(shell pwd)/coverage/html/c/index.html"
	@echo "Python Report:  file://$(shell pwd)/coverage/html/python/index.html"
	@echo "---"

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
	    Makefile README.md clean.sh start_all.sh \
	    src tests server_files

# CLI helpers
.PHONY: cli-install cli-uninstall
cli-install:
	python3 -m pip install --user pipx || true
	python3 -m pipx ensurepath || true
	python3 -m pipx install tools/cli || python3 -m pipx reinstall ming-drlms

cli-uninstall:
	python3 -m pipx uninstall ming-drlms || true

.PHONY: hook-install hook-uninstall
hook-install:
	@git config core.hooksPath .githooks
	@chmod +x .githooks/pre-commit || true
	@echo "Git hooks installed (core.hooksPath=.githooks)"

hook-uninstall:
	@git config --unset core.hooksPath || true
	@echo "Git hooks uninstalled"
