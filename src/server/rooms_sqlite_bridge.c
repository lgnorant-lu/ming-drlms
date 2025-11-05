#include "rooms_sqlite_bridge.h"
#include "rooms_utils.h"
#include <stdio.h>
#include <string.h>

static SQLiteStorage g_sqlite_storage = {0};
static int g_use_sqlite = 0;

int rooms_sqlite_bridge_init(const char *base_dir) {
    if (!base_dir || !*base_dir)
        return -1;
    char db_path[1024];
    snprintf(db_path, sizeof db_path, "%s/drlms.db", base_dir);
    if (sqlite_storage_init(&g_sqlite_storage, db_path) == 0) {
        g_use_sqlite = 1;
        fprintf(stderr, "SQLite storage initialized: %s\n", db_path);
        return 0;
    }
    g_use_sqlite = 0;
    fprintf(
        stderr,
        "Failed to initialize SQLite storage, falling back to file storage\n");
    return -1;
}

int rooms_is_sqlite_enabled(void) {
    return g_use_sqlite;
}

SQLiteStorage *rooms_get_sqlite_storage(void) {
    return &g_sqlite_storage;
}

void rooms_sqlite_sync_instance(SQLiteStorage *st, const char *instance_hex,
                                const char *room_name, int storage_policy,
                                int max_capacity, int state,
                                unsigned long long last_event_id) {
    if (!st || !instance_hex || !room_name)
        return;
    (void)sqlite_upsert_room_instance(st, instance_hex, room_name,
                                      storage_policy, max_capacity, state,
                                      last_event_id);
}

void rooms_sqlite_sync_room_totals(SQLiteStorage *st, const char *room_name,
                                   size_t total_instances, size_t total_subs,
                                   unsigned long long last_event_id) {
    if (!st || !room_name)
        return;
    (void)sqlite_update_room_aggregates(st, room_name, total_instances,
                                        total_subs, last_event_id);
}
