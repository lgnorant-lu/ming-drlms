#ifndef DRLMS_ROOMS_GC_H
#define DRLMS_ROOMS_GC_H

// Rooms GC thread manager: periodically invokes a provided callback
// to collect idle instances. Keeps idle_ttl/interval config central.

// Start GC thread; returns 0 on success. collect_cb must be thread-safe.
int rooms_gc_start(long idle_ttl, long interval, void (*collect_cb)(void));

// Stop GC thread gracefully.
void rooms_gc_stop(void);

// Immediate collection trigger (invokes callback synchronously if set).
void rooms_gc_collect_now(void);

// Accessor for current idle TTL (may be used by callers for decisions).
long rooms_gc_get_idle_ttl(void);

#endif // DRLMS_ROOMS_GC_H
