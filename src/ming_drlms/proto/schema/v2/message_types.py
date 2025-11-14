"""Additional message type constants for Ming DRLMS v2 protocol."""

# Existing constants are defined in ``common_pb2`` but that module is generated
# and may not be regenerated for every incremental protocol change. We define
# the new E2EE message type numbers here to keep Python and C code in sync.

MSG_TYPE_E2EE_GENERATE_KEYS_REQUEST = 500
MSG_TYPE_E2EE_GENERATE_KEYS_RESPONSE = 501
MSG_TYPE_E2EE_PREKEY_BUNDLE_REQUEST = 502
MSG_TYPE_E2EE_PREKEY_BUNDLE_RESPONSE = 503
MSG_TYPE_ROOM_MEMBER_LIST_REQUEST = 232
MSG_TYPE_ROOM_MEMBER_LIST_RESPONSE = 233

__all__ = [
    "MSG_TYPE_E2EE_GENERATE_KEYS_REQUEST",
    "MSG_TYPE_E2EE_GENERATE_KEYS_RESPONSE",
    "MSG_TYPE_E2EE_PREKEY_BUNDLE_REQUEST",
    "MSG_TYPE_E2EE_PREKEY_BUNDLE_RESPONSE",
    "MSG_TYPE_ROOM_MEMBER_LIST_REQUEST",
    "MSG_TYPE_ROOM_MEMBER_LIST_RESPONSE",
]
