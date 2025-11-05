#ifndef DRLMS_ROOMS_INTERNAL_H
#define DRLMS_ROOMS_INTERNAL_H

#include "platform/platform.h"
#include <time.h>
#include <stddef.h>
#include <stdint.h>

#include "rooms_instance.h" // for RoomInstance

// Internal Room definition shared by rooms.c and instance/GC modules
struct Room {
    platform_mutex_t mu;
    char name[65];
    char owner[64];
    platform_socket_t owner_fd;
    int policy;                  // 0=retain,1=delegate,2=teardown
    int storage_policy_template; // 0=persistent,1=ephemeral (future use)
    time_t created_at;
    time_t updated_at;
    size_t max_capacity_per_instance;
    size_t max_instances;
    size_t total_instances;
    size_t total_subs;
    unsigned long long last_event_id;
    size_t max_ephemeral_events;
    RoomInstance *instances;
};

typedef struct Room Room; // convenience alias

// Internal helpers exposed across rooms submodules
void rooms_apply_policy_on_owner_offline_if_needed(Room *room,
                                                   long long rate_bps);
const char *rooms_get_rooms_dir(void);

// Instance helpers that assume room mutex is already held
RoomInstance *rooms_inst_find_by_fd_locked(Room *room, platform_socket_t fd,
                                           InstanceUUID *out_uuid);

#endif // DRLMS_ROOMS_INTERNAL_H
