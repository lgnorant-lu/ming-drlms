#include "federation_internal.h"
#include <string.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

int federation_register_remote_subscriber(const char *room_name,
                                          const char *instance_id_hex,
                                          const char *remote_server_id) {
    if (!g_federation_initialized || !g_federation_config.enabled ||
        !g_federation_mutex_ready) {
        return -1;
    }

    platform_mutex_lock(&g_federation_mu);

    // Check if already registered
    RemoteSubscriber *curr = g_remote_subscribers;
    while (curr) {
        if (strcmp(curr->room_name, room_name) == 0 &&
            strcmp(curr->instance_id_hex, instance_id_hex) == 0 &&
            strcmp(curr->remote_server_id, remote_server_id) == 0) {
            if (curr->refcount < INT_MAX) {
                curr->refcount++;
            }
            platform_mutex_unlock(&g_federation_mu);
            return 0; // Already registered
        }
        curr = curr->next;
    }

    // Add new entry
    RemoteSubscriber *sub =
        (RemoteSubscriber *)calloc(1, sizeof(RemoteSubscriber));
    if (!sub) {
        platform_mutex_unlock(&g_federation_mu);
        return -1;
    }

    strncpy(sub->room_name, room_name, sizeof(sub->room_name) - 1);
    strncpy(sub->instance_id_hex, instance_id_hex,
            sizeof(sub->instance_id_hex) - 1);
    strncpy(sub->remote_server_id, remote_server_id,
            sizeof(sub->remote_server_id) - 1);
    sub->refcount = 1;

    sub->next = g_remote_subscribers;
    g_remote_subscribers = sub;

    platform_mutex_unlock(&g_federation_mu);

    fprintf(stderr,
            "[federation] Registered remote subscriber: room=%s, instance=%s, "
            "server=%s\n",
            room_name, instance_id_hex, remote_server_id);

    return 0;
}

int federation_unregister_remote_subscriber(const char *room_name,
                                            const char *instance_id_hex,
                                            const char *remote_server_id) {
    if (!g_federation_initialized || !g_federation_config.enabled ||
        !g_federation_mutex_ready) {
        return -1;
    }

    platform_mutex_lock(&g_federation_mu);

    RemoteSubscriber **prev_ptr = &g_remote_subscribers;
    RemoteSubscriber *curr = g_remote_subscribers;

    while (curr) {
        if (strcmp(curr->room_name, room_name) == 0 &&
            strcmp(curr->instance_id_hex, instance_id_hex) == 0 &&
            strcmp(curr->remote_server_id, remote_server_id) == 0) {
            if (curr->refcount > 1) {
                curr->refcount--;
            } else {
                *prev_ptr = curr->next;
                free(curr);
            }
            platform_mutex_unlock(&g_federation_mu);
            return 0;
        }
        prev_ptr = &curr->next;
        curr = curr->next;
    }

    platform_mutex_unlock(&g_federation_mu);
    return -1; // Not found
}

size_t federation_get_remote_servers(const char *room_name,
                                     const char *instance_id_hex,
                                     TrustedServer *out_servers,
                                     size_t capacity) {
    if (!g_federation_initialized || !g_federation_config.enabled ||
        !g_federation_mutex_ready) {
        return 0;
    }

    platform_mutex_lock(&g_federation_mu);

    size_t count = 0;
    RemoteSubscriber *curr = g_remote_subscribers;

    while (curr && count < capacity) {
        if (strcmp(curr->room_name, room_name) == 0 &&
            strcmp(curr->instance_id_hex, instance_id_hex) == 0) {

            // Find the corresponding trusted server
            for (size_t i = 0; i < g_federation_config.trusted_servers_count;
                 i++) {
                if (strcmp(g_federation_config.trusted_servers[i].server_id,
                           curr->remote_server_id) == 0) {
                    memcpy(&out_servers[count],
                           &g_federation_config.trusted_servers[i],
                           sizeof(TrustedServer));
                    count++;
                    break;
                }
            }
        }
        curr = curr->next;
    }

    platform_mutex_unlock(&g_federation_mu);
    return count;
}
