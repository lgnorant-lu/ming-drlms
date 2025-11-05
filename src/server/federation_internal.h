#ifndef DRLMS_FEDERATION_INTERNAL_H
#define DRLMS_FEDERATION_INTERNAL_H

#include "federation.h"
#include "platform/platform.h"

// Internal data structures and globals shared across federation modules
typedef struct RemoteSubscriber {
    char room_name[65];
    char instance_id_hex[33];
    char remote_server_id[MAX_SERVER_ID_LEN];
    int refcount;
    struct RemoteSubscriber *next;
} RemoteSubscriber;

// Global federation state (defined in federation.c)
extern FederationConfig g_federation_config;
extern RemoteSubscriber *g_remote_subscribers;
extern platform_mutex_t g_federation_mu;
extern int g_federation_initialized;
extern int g_federation_mutex_ready;

#endif // DRLMS_FEDERATION_INTERNAL_H
