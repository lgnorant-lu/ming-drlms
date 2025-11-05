#ifndef MP2_ROOMS_H
#define MP2_ROOMS_H

#include <stdint.h>

#include "platform/platform.h"

int mp2_rooms_handle_subscribe(platform_socket_t fd,
                               const unsigned char *payload,
                               uint32_t payload_len);

int mp2_rooms_handle_publish(platform_socket_t fd, const unsigned char *payload,
                             uint32_t payload_len);

int mp2_rooms_handle_room_info(platform_socket_t fd,
                               const unsigned char *payload,
                               uint32_t payload_len);

int mp2_rooms_handle_room_list(platform_socket_t fd,
                               const unsigned char *payload,
                               uint32_t payload_len);

int mp2_rooms_handle_room_create(platform_socket_t fd,
                                 const unsigned char *payload,
                                 uint32_t payload_len);

int mp2_rooms_handle_set_policy(platform_socket_t fd,
                                const unsigned char *payload,
                                uint32_t payload_len);

int mp2_rooms_handle_set_storage_policy(platform_socket_t fd,
                                        const unsigned char *payload,
                                        uint32_t payload_len);

int mp2_rooms_handle_transfer_owner(platform_socket_t fd,
                                    const unsigned char *payload,
                                    uint32_t payload_len);

int mp2_rooms_handle_history_request(platform_socket_t fd,
                                     const unsigned char *payload,
                                     uint32_t payload_len);

int mp2_rooms_handle_file_publish_begin(platform_socket_t fd,
                                        const unsigned char *payload,
                                        uint32_t payload_len);

int mp2_rooms_handle_file_publish_chunk(platform_socket_t fd,
                                        const unsigned char *payload,
                                        uint32_t payload_len);

int mp2_rooms_handle_file_publish_commit(platform_socket_t fd,
                                         const unsigned char *payload,
                                         uint32_t payload_len);

int mp2_rooms_handle_file_download(platform_socket_t fd,
                                   const unsigned char *payload,
                                   uint32_t payload_len);

#endif /* MP2_ROOMS_H */
