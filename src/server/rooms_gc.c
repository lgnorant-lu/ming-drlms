#include <stdlib.h>
#include <stdio.h>
#include "platform/thread.h"
#include "rooms_gc.h"
#include "rooms_internal.h"
#include "rooms_instance.h"
#include "rooms_utils.h"
#include "sqlite_storage.h"
#include "logger.h"
// Accessors from rooms.c (not exposed via rooms.h)
extern int rooms_is_sqlite_enabled(void);
extern SQLiteStorage *rooms_get_sqlite_storage(void);
extern void rooms_instance_destroy_unlink_locked(Room *room,
                                                 RoomInstance *instance);
#include <time.h>
#if defined(_WIN32)
#include <windows.h>
#else
#include <unistd.h>
#endif

static volatile int g_gc_running = 0;
static long g_idle_ttl = 86400;
static long g_gc_interval = 60;
static platform_thread_t g_gc_thread;
static void (*g_collect_cb)(void) = 0;

typedef struct RoomsGcCtx {
    time_t now;
} RoomsGcCtx;

static void sleep_microseconds(unsigned long long usec);

static void rooms_gc_iter_room(Room *room, const char *room_name, void *pctx) {
    RoomsGcCtx *c = (RoomsGcCtx *)pctx;
    if (!c)
        return;
    (void)room_name;
    platform_mutex_lock(&room->mu);
    RoomInstance *inst = room->instances;
    while (inst) {
        RoomInstance *next = inst->next;
        InstanceUUID uuid_copy = inst->instance_id;
        platform_mutex_lock(&inst->mu);
        IgniteExpiryNotice ignite_notices[8] = {0};
        size_t ignite_notice_count =
            rooms_instance_collect_expired_ignite_locked(
                inst, c->now, ignite_notices,
                sizeof ignite_notices / sizeof ignite_notices[0]);
        size_t subs = inst->subs_len;
        time_t last_active = inst->last_active;
        int storage_policy = inst->storage_policy;
        platform_mutex_unlock(&inst->mu);
        if (ignite_notice_count > 0) {
            char inst_hex_buf[33];
            rooms_uuid_to_hex(&uuid_copy, inst_hex_buf);
            char ts[64];
            rfc3339_time_local(ts, sizeof ts);
            for (size_t n = 0; n < ignite_notice_count; ++n) {
                char evt_buf[256];
                int evl =
                    snprintf(evt_buf, sizeof evt_buf,
                             "EVT|IGNITE_REJECTED|%s|%s|%s|%s\n", room_name,
                             inst_hex_buf, ts, ignite_notices[n].request_id);
                if (evl > 0 && (size_t)evl < sizeof evt_buf) {
                    rooms_emit_to_presence(inst,
                                           ignite_notices[n].presence_token,
                                           evt_buf, (size_t)evl);
                }
            }
        }
        long ttl = rooms_gc_get_idle_ttl();
        int should_destroy =
            (subs == 0) && (storage_policy == 1 || ttl == 0 ||
                            (ttl > 0 && (c->now - last_active) >= ttl));
        if (should_destroy) {
            rooms_instance_destroy_unlink_locked(room, inst);
            if (rooms_is_sqlite_enabled()) {
                char instance_hex[33];
                rooms_uuid_to_hex(&uuid_copy, instance_hex);
                (void)sqlite_mark_room_instance_destroyed(
                    rooms_get_sqlite_storage(), instance_hex);
            }
        }
        inst = next;
    }
    room_update_aggregates_locked(room);
    if (rooms_is_sqlite_enabled()) {
        (void)sqlite_update_room_aggregates(
            rooms_get_sqlite_storage(), room->name, room->total_instances,
            room->total_subs, room->last_event_id);
    }
    platform_mutex_unlock(&room->mu);
}

static void *rooms_gc_thread_main(void *arg) {
    (void)arg;
    while (g_gc_running) {
        long interval = g_gc_interval;
        if (interval <= 0)
            interval = 60;
        sleep_microseconds((unsigned long long)interval * 1000000ULL);
        if (!g_gc_running)
            break;
        if (g_collect_cb)
            g_collect_cb();
    }
    return NULL;
}

static void rooms_gc_collect_default(void) {
    if (rooms_gc_get_idle_ttl() < 0)
        return;
    RoomsGcCtx ctx = {time(NULL)};
    rooms_for_each(rooms_gc_iter_room, &ctx);
}

int rooms_gc_start(long idle_ttl, long interval, void (*collect_cb)(void)) {
    g_idle_ttl = idle_ttl;
    g_gc_interval = interval;
    g_collect_cb = collect_cb ? collect_cb : rooms_gc_collect_default;
    if (g_gc_running)
        return 0;
    g_gc_running = 1;
    if (platform_thread_create(&g_gc_thread, rooms_gc_thread_main, NULL) != 0) {
        g_gc_running = 0;
        LOG_ERROR("rooms_gc: failed to start GC thread");
        return -1;
    }
    // Detach so it can exit on its own when g_gc_running becomes 0
    platform_thread_detach(g_gc_thread);
    return 0;
}

void rooms_gc_stop(void) {
    if (!g_gc_running)
        return;
    g_gc_running = 0;
}

void rooms_gc_collect_now(void) {
    if (g_collect_cb)
        g_collect_cb();
}

long rooms_gc_get_idle_ttl(void) {
    return g_idle_ttl;
}

static void sleep_microseconds(unsigned long long usec) {
#if defined(_WIN32)
    DWORD ms = (DWORD)(usec / 1000ULL);
    if (ms == 0 && usec > 0)
        ms = 1; // minimum sleep
    Sleep(ms);
#else
    struct timespec ts;
    ts.tv_sec = (time_t)(usec / 1000000ULL);
    ts.tv_nsec = (long)((usec % 1000000ULL) * 1000ULL);
    nanosleep(&ts, NULL);
#endif
}
