# -*- coding: utf-8 -*-
"""Generated-like module for schema/v2/e2ee.proto."""

from google.protobuf import descriptor_pb2 as _descriptor_pb2
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database

_sym_db = _symbol_database.Default()

_FILE_DESCRIPTOR_PROTO = _descriptor_pb2.FileDescriptorProto()
_FILE_DESCRIPTOR_PROTO.name = "schema/v2/e2ee.proto"
_FILE_DESCRIPTOR_PROTO.package = "mingdrlms.v2"
_FILE_DESCRIPTOR_PROTO.syntax = "proto3"

_req = _FILE_DESCRIPTOR_PROTO.message_type.add()
_req.name = "E2EEGenerateKeysRequest"
_field = _req.field.add()
_field.name = "user_name"
_field.number = 1
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_STRING
_field = _req.field.add()
_field.name = "force_regenerate"
_field.number = 2
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_BOOL

_resp = _FILE_DESCRIPTOR_PROTO.message_type.add()
_resp.name = "E2EEGenerateKeysResponse"
_field = _resp.field.add()
_field.name = "code"
_field.number = 1
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_INT32
_field = _resp.field.add()
_field.name = "message"
_field.number = 2
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_STRING
_field = _resp.field.add()
_field.name = "registration_id"
_field.number = 3
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_UINT32
_field = _resp.field.add()
_field.name = "pre_key_count"
_field.number = 4
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_UINT32

_bundle_req = _FILE_DESCRIPTOR_PROTO.message_type.add()
_bundle_req.name = "E2EEPreKeyBundleRequest"
_field = _bundle_req.field.add()
_field.name = "user_name"
_field.number = 1
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_STRING

_bundle_resp = _FILE_DESCRIPTOR_PROTO.message_type.add()
_bundle_resp.name = "E2EEPreKeyBundleResponse"
_field = _bundle_resp.field.add()
_field.name = "code"
_field.number = 1
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_INT32
_field = _bundle_resp.field.add()
_field.name = "message"
_field.number = 2
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_STRING
_field = _bundle_resp.field.add()
_field.name = "identity_key"
_field.number = 3
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_BYTES
_field = _bundle_resp.field.add()
_field.name = "registration_id"
_field.number = 4
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_UINT32
_field = _bundle_resp.field.add()
_field.name = "device_id"
_field.number = 5
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_UINT32
_field = _bundle_resp.field.add()
_field.name = "pre_key_id"
_field.number = 6
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_UINT32
_field = _bundle_resp.field.add()
_field.name = "pre_key_public"
_field.number = 7
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_BYTES
_field = _bundle_resp.field.add()
_field.name = "signed_pre_key_id"
_field.number = 8
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_UINT32
_field = _bundle_resp.field.add()
_field.name = "signed_pre_key_public"
_field.number = 9
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_BYTES
_field = _bundle_resp.field.add()
_field.name = "signed_pre_key_signature"
_field.number = 10
_field.label = _descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_field.type = _descriptor_pb2.FieldDescriptorProto.TYPE_BYTES

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    _FILE_DESCRIPTOR_PROTO.SerializeToString()
)

E2EEGenerateKeysRequest = _reflection.GeneratedProtocolMessageType(
    "E2EEGenerateKeysRequest",
    (_message.Message,),
    {
        "DESCRIPTOR": DESCRIPTOR.message_types_by_name["E2EEGenerateKeysRequest"],
        "__module__": __name__,
    },
)
_sym_db.RegisterMessage(E2EEGenerateKeysRequest)

E2EEGenerateKeysResponse = _reflection.GeneratedProtocolMessageType(
    "E2EEGenerateKeysResponse",
    (_message.Message,),
    {
        "DESCRIPTOR": DESCRIPTOR.message_types_by_name["E2EEGenerateKeysResponse"],
        "__module__": __name__,
    },
)
_sym_db.RegisterMessage(E2EEGenerateKeysResponse)

E2EEPreKeyBundleRequest = _reflection.GeneratedProtocolMessageType(
    "E2EEPreKeyBundleRequest",
    (_message.Message,),
    {
        "DESCRIPTOR": DESCRIPTOR.message_types_by_name["E2EEPreKeyBundleRequest"],
        "__module__": __name__,
    },
)
_sym_db.RegisterMessage(E2EEPreKeyBundleRequest)

E2EEPreKeyBundleResponse = _reflection.GeneratedProtocolMessageType(
    "E2EEPreKeyBundleResponse",
    (_message.Message,),
    {
        "DESCRIPTOR": DESCRIPTOR.message_types_by_name["E2EEPreKeyBundleResponse"],
        "__module__": __name__,
    },
)
_sym_db.RegisterMessage(E2EEPreKeyBundleResponse)

__all__ = [
    "E2EEGenerateKeysRequest",
    "E2EEGenerateKeysResponse",
    "E2EEPreKeyBundleRequest",
    "E2EEPreKeyBundleResponse",
]
