#ifndef DRLMS_FEDERATION_H
#define DRLMS_FEDERATION_H

#include <stddef.h>
#include <stdint.h>
#include "platform/platform.h"

#ifdef HAVE_PROTOBUF_C
#include "generated/schema/v2/room.pb-c.h"
#else
typedef enum {
    MINGDRLMS__V2__ROOM_EVENT_KIND__UNKNOWN = 0
} Mingdrlms__V2__RoomEventKind;
typedef struct _Mingdrlms__V2__RoomFileMetadata Mingdrlms__V2__RoomFileMetadata;
#endif
#include "rooms.h"

// Federation configuration
#define MAX_TRUSTED_SERVERS 32
#define MAX_SERVER_ID_LEN 64
#define MAX_BEARER_TOKEN_LEN 128
#define MAX_HOSTNAME_LEN 256

typedef struct {
    char server_id[MAX_SERVER_ID_LEN];
    char host[MAX_HOSTNAME_LEN];
    int port;
    char bearer_token[MAX_BEARER_TOKEN_LEN];
} TrustedServer;

typedef struct {
    int enabled;
    char server_id[MAX_SERVER_ID_LEN];
    char bearer_token[MAX_BEARER_TOKEN_LEN];
    TrustedServer trusted_servers[MAX_TRUSTED_SERVERS];
    size_t trusted_servers_count;
} FederationConfig;

// Initialize federation subsystem
int federation_init(const FederationConfig *config);

// Shutdown federation subsystem
void federation_shutdown(void);

// Verify S2S bearer token
int federation_verify_token(const char *bearer_token);

// Forward a publish event to remote servers that have subscribers
// Returns 0 on success, -1 on error
int federation_forward_publish(const char *room_name,
                               const char *instance_id_hex, uint64_t event_id,
                               const char *timestamp, const char *sender_user,
                               const char *display_token,
                               const unsigned char *payload, size_t payload_len,
                               const char *sha_hex, int ephemeral,
                               Mingdrlms__V2__RoomEventKind event_kind,
                               const char *filename, uint64_t file_size_bytes);

// Handle incoming S2S publish request (called by server when receiving
// MSG_TYPE_S2S_PUB_REQUEST) Returns number of local subscribers forwarded to,
// or -1 on error
int federation_handle_s2s_publish(
    const char *bearer_token, const char *room_name,
    const char *instance_id_hex, uint64_t event_id, const char *timestamp,
    const char *sender_user, const char *display_token,
    const unsigned char *payload, size_t payload_len, const char *sha_hex,
    Mingdrlms__V2__RoomEventKind event_kind,
    const Mingdrlms__V2__RoomFileMetadata *file_meta, int ephemeral);

// Handle incoming S2S subscribe/unsubscribe request
// subscribe != 0 registers; subscribe == 0 unregisters
int federation_handle_s2s_subscribe(const char *bearer_token,
                                    const char *room_name,
                                    const char *instance_id_hex,
                                    const char *remote_server_id,
                                    int subscribe);

// Notify trusted servers that we have (or no longer have) local subscribers
int federation_notify_subscription(const char *room_name,
                                   const char *instance_id_hex, int subscribe);

// Load federation configuration from YAML file (returns 0 on success)
int federation_load_config(const char *config_path,
                           FederationConfig *out_config);

// Accessor for current federation configuration (NULL if not initialized)
const FederationConfig *federation_get_config(void);

// Register a remote subscriber for a room instance
// This tracks that a remote server has subscribers for this room
int federation_register_remote_subscriber(const char *room_name,
                                          const char *instance_id_hex,
                                          const char *remote_server_id);

// Unregister a remote subscriber
int federation_unregister_remote_subscriber(const char *room_name,
                                            const char *instance_id_hex,
                                            const char *remote_server_id);

// Get list of remote servers that have subscribers for a room instance
// Returns number of servers, fills out_servers array (up to capacity)
size_t federation_get_remote_servers(const char *room_name,
                                     const char *instance_id_hex,
                                     TrustedServer *out_servers,
                                     size_t capacity);

#endif // DRLMS_FEDERATION_H
