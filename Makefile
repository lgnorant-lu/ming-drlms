CC = gcc
CFLAGS = -Wall -Wextra -pthread -Werror -Wno-deprecated-declarations
CPPFLAGS = -Isrc -Isrc/libipc -Isrc/platform/include

UNAME_S := $(strip $(shell uname -s 2>/dev/null))

LIBS_COMMON =
LIBS_SERVER = -lcrypto -largon2 -lsqlite3
LIBS_AGENT = -lcrypto
PLATFORM_EXTRA_LIBS =

ifeq ($(OS),Windows_NT)
	PLATFORM = windows
	PLATFORM_SRC = src/platform/windows/thread.c \
				   src/platform/windows/ipc.c \
				   src/platform/windows/net.c \
				   src/platform/windows/file.c \
				   src/platform/windows/win_error.c
	PLATFORM_LIB = libplatform_windows.a
	PLATFORM_EXTRA_LIBS += -lws2_32
else ifeq ($(UNAME_S),Linux)
	PLATFORM = linux
	PLATFORM_SRC = src/platform/linux/thread.c \
				   src/platform/linux/ipc.c \
				   src/platform/linux/net.c \
				   src/platform/linux/file.c
	PLATFORM_LIB = libplatform_linux.a
	LIBS_COMMON += -lrt
else ifeq ($(UNAME_S),Darwin)
	PLATFORM = macos
	PLATFORM_SRC = src/platform/macos/thread.c \
				   src/platform/macos/ipc.c \
				   src/platform/macos/net.c \
				   src/platform/macos/file.c
	PLATFORM_LIB = libplatform_macos.a
else
	$(error Unsupported platform: $(UNAME_S))
endif

LIBS_AGENT += $(PLATFORM_EXTRA_LIBS)
LIBS_SERVER += $(LIBS_COMMON) $(PLATFORM_EXTRA_LIBS)

PLATFORM_OBJS = $(PLATFORM_SRC:.c=.o)

# install destinations
PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib
INCLUDEDIR ?= $(PREFIX)/include
PKGCONFIGDIR ?= $(LIBDIR)/pkgconfig

SRC_LIBIPC = src/libipc/shared_buffer.c
SRC_SERVER = src/server/log_collector_server.c src/server/rooms.c src/server/sqlite_storage.c
SRC_AGENT = src/agent/log_agent.c
SRC_TOOLS = src/tools/proc_launcher.c src/tools/log_consumer.c src/tools/ipc_sender.c

# All C source files for coverage analysis
C_SOURCES = $(SRC_LIBIPC) $(SRC_SERVER) $(SRC_AGENT) $(SRC_TOOLS)

all: $(PLATFORM_LIB) libipc.a libipc.so log_collector_server log_agent proc_launcher log_consumer ipc_sender

%.o: %.c
	$(CC) $(CFLAGS) $(CPPFLAGS) -fPIC -c $< -o $@

libipc.a: $(SRC_LIBIPC:.c=.o)
	ar rcs $@ $^

libipc.so: $(SRC_LIBIPC:.c=.o) $(PLATFORM_LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) -shared -o $@ $(SRC_LIBIPC:.c=.o) $(PLATFORM_LIB) $(LIBS_COMMON) $(PLATFORM_EXTRA_LIBS)

$(PLATFORM_LIB): $(PLATFORM_OBJS)
	ar rcs $@ $^

log_collector_server: $(SRC_SERVER) libipc.a $(PLATFORM_LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $(SRC_SERVER) -L. -lipc $(PLATFORM_LIB) $(LIBS_SERVER) -Wl,-rpath,'$$ORIGIN'

log_agent: $(SRC_AGENT) $(PLATFORM_LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $(SRC_AGENT) $(PLATFORM_LIB) $(LIBS_AGENT) -Wl,-rpath,'$$ORIGIN'

proc_launcher: src/tools/proc_launcher.c
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ src/tools/proc_launcher.c -Wl,-rpath,'$$ORIGIN'

log_consumer: src/tools/log_consumer.c libipc.a $(PLATFORM_LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $< -L. -lipc $(PLATFORM_LIB) $(LIBS_COMMON) $(PLATFORM_EXTRA_LIBS) -Wl,-rpath,'$$ORIGIN'

ipc_sender: src/tools/ipc_sender.c libipc.a $(PLATFORM_LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $< -L. -lipc $(PLATFORM_LIB) $(LIBS_COMMON) $(PLATFORM_EXTRA_LIBS) -Wl,-rpath,'$$ORIGIN'

debug:
	$(MAKE) CFLAGS="$(CFLAGS) -g -O0 -DDEBUG" all

clean:
	find . -type f \( -name "*.o" -o -name "*.a" -o -name "*.so" -o -name "*.gcno" -o -name "*.gcda" -o -name "*.gcov" \) -delete || true
	rm -f log_collector_server log_agent proc_launcher log_consumer ipc_sender tests/test_ipc_suite $(PLATFORM_LIB) || true
	rm -rf coverage .coverage

.PHONY: all debug clean test coverage

# Tests & Coverage
TESTS = tests/test_ipc_suite

tests/test_ipc_suite: tests/test_ipc_suite.c libipc.a $(PLATFORM_LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $< -L. -lipc $(PLATFORM_LIB) $(LIBS_COMMON) $(PLATFORM_EXTRA_LIBS) -lcrypto -Wl,-rpath,'$$ORIGIN'

test: $(TESTS) log_agent log_collector_server ipc_sender log_consumer
	@echo "Running C unit tests..."
	DRLMS_SHM_KEY=0x4c4f4754 LD_LIBRARY_PATH=. DYLD_LIBRARY_PATH=. ./tests/test_ipc_suite
	@echo "Running C protocol integration tests..."
	chmod +x tests/test_server_protocol.sh && HOST=127.0.0.1 PORT=8080 bash -lc 'LD_LIBRARY_PATH=. DYLD_LIBRARY_PATH=. ./tests/test_server_protocol.sh $${HOST} $${PORT}'
	@echo "Running Python E2E tests..."
	chmod +x tests/test_cli_e2e.sh && HOST=127.0.0.1 PORT=8080 bash -lc './tests/test_cli_e2e.sh'

coverage:
	@echo "--- Generating comprehensive C and Python coverage report using CMake ---"
	bash scripts/run_coverage.sh

# ------------------------------------------------------------
# GUI PoC helpers
# ------------------------------------------------------------
.PHONY: gui_poc
gui_poc: all
	@echo "--- Building GUI PoC dependencies ---"
	$(MAKE) -C gui_poc all

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
	@echo "Libs: -L$${libdir} -lipc $(LIBS_COMMON) -lpthread $(PLATFORM_EXTRA_LIBS)" >> libipc.pc
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
	    Makefile README.md \
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
