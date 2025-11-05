#ifndef MP2_ROOMS_HISTORY_H
#define MP2_ROOMS_HISTORY_H

#include <stdint.h>
#include "platform/platform.h"
#include "rooms.h"

#ifdef __cplusplus
extern "C" {
#endif

#define MP2_HISTORY_DEFAULT_LIMIT 50

// Stream history events to a client. Includes both text and files depending on
// flags.
int mp2_rooms_stream_history(platform_socket_t fd, Room *room,
                             RoomInstance *instance, const char *room_name,
                             const char *viewer_user, uint64_t since_id,
                             size_t client_limit, int include_text,
                             int include_files);

// Convenience wrapper used by subscribe flow.
int mp2_rooms_send_history(platform_socket_t client_fd, const char *room_name,
                           RoomInstance *instance, const char *viewer_user,
                           int64_t since_id, size_t limit);

#ifdef __cplusplus
}
#endif

#endif // MP2_ROOMS_HISTORY_H
