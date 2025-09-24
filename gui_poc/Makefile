# GUI PoC Makefile (modularized)

.PHONY: all bins build_root

ROOT := ..
OUTDIR := assets/bin/linux/x86_64

all: bins

build_root:
	$(MAKE) -C $(ROOT) all

bins: build_root
	mkdir -p $(OUTDIR)
	cp -f $(ROOT)/log_collector_server $(OUTDIR)/
	cp -f $(ROOT)/log_agent $(OUTDIR)/
	cp -f $(ROOT)/ipc_sender $(OUTDIR)/
	cp -f $(ROOT)/log_consumer $(OUTDIR)/
	cp -f $(ROOT)/libipc.so $(OUTDIR)/


