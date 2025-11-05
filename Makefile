CC = gcc
CFLAGS = -Wall -Wextra -pthread -Werror -Wno-deprecated-declarations
CPPFLAGS = -Isrc -Isrc/libipc -Isrc/platform/include

UNAME_S := $(strip $(shell uname -s 2>/dev/null))

LIBS_COMMON =
LIBS_SERVER = -lcrypto -largon2 -lsqlite3 -lprotobuf-c
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

# local build output directory for executables (avoid cluttering repo root)
OUTDIR ?= bin

# -----------------------------------------------------------------------------
# Make wrapper: CMake is the canonical build. To use legacy Make targets, run
#   make ALLOW_LEGACY=1 <target>
# -----------------------------------------------------------------------------
ifndef ALLOW_LEGACY
.PHONY: all cmake clean
all:
	@echo "[error] Make-based build is deprecated. Use CMake instead:" >&2
	@echo "  rm -rf build && cmake -S . -B build" >&2
	@echo "  cmake --build build --target proto_gen log_collector_server -j" >&2
	@echo "(or run: make ALLOW_LEGACY=1 all)" >&2
	@exit 2

cmake:
	@mkdir -p build
	@cmake -S . -B build
	@cmake --build build --target proto_gen log_collector_server -j

clean:
	rm -rf build $(OUTDIR) coverage .coverage libipc.a libipc.so libplatform_linux.a

# stop here; legacy rules are disabled unless ALLOW_LEGACY=1
else

SRC_LIBIPC = src/libipc/shared_buffer.c
SRC_SERVER = src/server/log_collector_server.c \
	src/server/mp2_auth.c \
	src/server/mp2_dispatcher.c \
	src/server/mp2_protocol.c \
	src/server/mp2_rooms.c \
	src/server/rooms.c \
	src/server/sqlite_storage.c \
	$(PROTO_C_SRCS)
SRC_AGENT = src/agent/log_agent.c
SRC_TOOLS = src/tools/proc_launcher.c src/tools/log_consumer.c src/tools/ipc_sender.c

# All C source files for coverage analysis
C_SOURCES = $(SRC_LIBIPC) $(SRC_SERVER) $(SRC_AGENT) $(SRC_TOOLS)

all: $(PLATFORM_LIB) libipc.a libipc.so $(OUTDIR)/log_collector_server $(OUTDIR)/log_agent $(OUTDIR)/proc_launcher $(OUTDIR)/log_consumer $(OUTDIR)/ipc_sender
PROTO_DIR = schema/v2
PROTO_SRCS = $(wildcard $(PROTO_DIR)/*.proto)
PROTO_C_SRCS = $(patsubst $(PROTO_DIR)/%.proto,src/generated/%.pb-c.c,$(PROTO_SRCS))
PROTO_C_HDRS = $(patsubst $(PROTO_DIR)/%.proto,src/generated/%.pb-c.h,$(PROTO_SRCS))

src/generated/%.pb-c.c src/generated/%.pb-c.h: $(PROTO_DIR)/%.proto
	@mkdir -p src/generated
	protoc-c --c_out=src/generated -I. -I$(PROTO_DIR) $<

proto: $(PROTO_C_SRCS) $(PROTO_C_HDRS)


%.o: %.c
	$(CC) $(CFLAGS) $(CPPFLAGS) -fPIC -c $< -o $@

libipc.a: $(SRC_LIBIPC:.c=.o)
	ar rcs $@ $^

libipc.so: $(SRC_LIBIPC:.c=.o) $(PLATFORM_LIB)
	$(CC) $(CFLAGS) $(CPPFLAGS) -shared -o $@ $(SRC_LIBIPC:.c=.o) $(PLATFORM_LIB) $(LIBS_COMMON) $(PLATFORM_EXTRA_LIBS)

$(PLATFORM_LIB): $(PLATFORM_OBJS)
	ar rcs $@ $^

$(OUTDIR)/log_collector_server: $(SRC_SERVER) libipc.a $(PLATFORM_LIB)
	@mkdir -p $(OUTDIR)
	$(CC) $(CFLAGS) $(CPPFLAGS) -Isrc/generated -o $@ $(SRC_SERVER) -L. -lipc $(PLATFORM_LIB) $(LIBS_SERVER) -Wl,-rpath,'$$ORIGIN'

$(OUTDIR)/log_agent: $(SRC_AGENT) $(PLATFORM_LIB)
	@mkdir -p $(OUTDIR)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $(SRC_AGENT) $(PLATFORM_LIB) $(LIBS_AGENT) -Wl,-rpath,'$$ORIGIN'

$(OUTDIR)/proc_launcher: src/tools/proc_launcher.c
	@mkdir -p $(OUTDIR)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ src/tools/proc_launcher.c -Wl,-rpath,'$$ORIGIN'

$(OUTDIR)/log_consumer: src/tools/log_consumer.c libipc.a $(PLATFORM_LIB)
	@mkdir -p $(OUTDIR)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $< -L. -lipc $(PLATFORM_LIB) $(LIBS_COMMON) $(PLATFORM_EXTRA_LIBS) -Wl,-rpath,'$$ORIGIN'

$(OUTDIR)/ipc_sender: src/tools/ipc_sender.c libipc.a $(PLATFORM_LIB)
	@mkdir -p $(OUTDIR)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $< -L. -lipc $(PLATFORM_LIB) $(LIBS_COMMON) $(PLATFORM_EXTRA_LIBS) -Wl,-rpath,'$$ORIGIN'

debug:
	$(MAKE) CFLAGS="$(CFLAGS) -g -O0 -DDEBUG" all

clean:
	find . -type f \( -name "*.o" -o -name "*.a" -o -name "*.so" -o -name "*.gcno" -o -name "*.gcda" -o -name "*.gcov" \) -delete || true
	rm -f $(OUTDIR)/log_collector_server $(OUTDIR)/log_agent $(OUTDIR)/proc_launcher $(OUTDIR)/log_consumer $(OUTDIR)/ipc_sender tests/test_ipc_suite $(PLATFORM_LIB) || true
	rm -rf coverage .coverage $(OUTDIR)

endif

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
