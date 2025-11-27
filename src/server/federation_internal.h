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

// Federation Async Task Queue
typedef enum { FED_TASK_NOTIFY_SUB, FED_TASK_FORWARD_PUB } FederationTaskType;

typedef struct {
    FederationTaskType type;
    char room_name[65];
    char instance_id_hex[33];
    int subscribe; // For NOTIFY_SUB

    // For FORWARD_PUB
    uint64_t event_id;
    char timestamp[64];
    char sender_user[64];
    char display_token[64];
    unsigned char *payload;
    size_t payload_len;
    char sha_hex[65];
    int ephemeral;
    int event_kind; // Mingdrlms__V2__RoomEventKind
    char filename[256];
    uint64_t file_size_bytes;
} FederationTask;

// Queue functions (implemented in federation.c)
void federation_queue_push(const FederationTask *task);
void federation_worker_start(void);
void federation_worker_stop(void);

// Internal perform functions (implemented in federation_publish.c)
int federation_perform_notify_subscription(const char *room_name,
                                           const char *instance_id_hex,
                                           int subscribe);
int federation_perform_forward_publish(
    const char *room_name, const char *instance_id_hex, uint64_t event_id,
    const char *timestamp, const char *sender_user, const char *display_token,
    const unsigned char *payload, size_t payload_len, const char *sha_hex,
    int ephemeral, int event_kind, const char *filename,
    uint64_t file_size_bytes);

#endif // DRLMS_FEDERATION_INTERNAL_H
