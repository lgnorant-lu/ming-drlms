#ifndef DRLMS_ROOMS_SQLITE_BRIDGE_H
#define DRLMS_ROOMS_SQLITE_BRIDGE_H

#include "sqlite_storage.h"

// Initialize SQLite storage and toggle enabled flag. Returns 0 on success, -1
// on failure.
int rooms_sqlite_bridge_init(const char *base_dir);

// Accessors used by internal modules
int rooms_is_sqlite_enabled(void);
SQLiteStorage *rooms_get_sqlite_storage(void);

// Glue helpers used by state to sync aggregates
void rooms_sqlite_sync_instance(SQLiteStorage *st, const char *instance_hex,
                                const char *room_name, int storage_policy,
                                int max_capacity, int state,
                                unsigned long long last_event_id);

void rooms_sqlite_sync_room_totals(SQLiteStorage *st, const char *room_name,
                                   size_t total_instances, size_t total_subs,
                                   unsigned long long last_event_id);

#endif // DRLMS_ROOMS_SQLITE_BRIDGE_H
