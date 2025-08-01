import utils_pb2 as _utils_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class HttpRequest(_message.Message):
    __slots__ = ["requestId", "method", "path", "headers", "body", "isFinalChunk", "chunkIndex", "chunkOffset"]
    class HeadersEntry(_message.Message):
        __slots__ = ["key", "value"]
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    REQUESTID_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    HEADERS_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    ISFINALCHUNK_FIELD_NUMBER: _ClassVar[int]
    CHUNKINDEX_FIELD_NUMBER: _ClassVar[int]
    CHUNKOFFSET_FIELD_NUMBER: _ClassVar[int]
    requestId: str
    method: str
    path: str
    headers: _containers.ScalarMap[str, str]
    body: bytes
    isFinalChunk: bool
    chunkIndex: int
    chunkOffset: int
    def __init__(self, requestId: _Optional[str] = ..., method: _Optional[str] = ..., path: _Optional[str] = ..., headers: _Optional[_Mapping[str, str]] = ..., body: _Optional[bytes] = ..., isFinalChunk: bool = ..., chunkIndex: _Optional[int] = ..., chunkOffset: _Optional[int] = ...) -> None: ...

class HttpResponse(_message.Message):
    __slots__ = ["requestId", "statusCode", "headers", "body", "isFinalChunk", "chunkIndex", "chunkOffset"]
    class HeadersEntry(_message.Message):
        __slots__ = ["key", "value"]
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    REQUESTID_FIELD_NUMBER: _ClassVar[int]
    STATUSCODE_FIELD_NUMBER: _ClassVar[int]
    HEADERS_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    ISFINALCHUNK_FIELD_NUMBER: _ClassVar[int]
    CHUNKINDEX_FIELD_NUMBER: _ClassVar[int]
    CHUNKOFFSET_FIELD_NUMBER: _ClassVar[int]
    requestId: str
    statusCode: int
    headers: _containers.ScalarMap[str, str]
    body: bytes
    isFinalChunk: bool
    chunkIndex: int
    chunkOffset: int
    def __init__(self, requestId: _Optional[str] = ..., statusCode: _Optional[int] = ..., headers: _Optional[_Mapping[str, str]] = ..., body: _Optional[bytes] = ..., isFinalChunk: bool = ..., chunkIndex: _Optional[int] = ..., chunkOffset: _Optional[int] = ...) -> None: ...

class HttpAbort(_message.Message):
    __slots__ = ["requestId", "reason"]
    REQUESTID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    requestId: str
    reason: str
    def __init__(self, requestId: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...

class TunnelMessage(_message.Message):
    __slots__ = ["authReq", "authRsp", "request", "response", "abort", "heartbeat"]
    AUTHREQ_FIELD_NUMBER: _ClassVar[int]
    AUTHRSP_FIELD_NUMBER: _ClassVar[int]
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_FIELD_NUMBER: _ClassVar[int]
    ABORT_FIELD_NUMBER: _ClassVar[int]
    HEARTBEAT_FIELD_NUMBER: _ClassVar[int]
    authReq: _utils_pb2.AuthReq
    authRsp: _utils_pb2.AuthRsp
    request: HttpRequest
    response: HttpResponse
    abort: HttpAbort
    heartbeat: _utils_pb2.Heartbeat
    def __init__(self, authReq: _Optional[_Union[_utils_pb2.AuthReq, _Mapping]] = ..., authRsp: _Optional[_Union[_utils_pb2.AuthRsp, _Mapping]] = ..., request: _Optional[_Union[HttpRequest, _Mapping]] = ..., response: _Optional[_Union[HttpResponse, _Mapping]] = ..., abort: _Optional[_Union[HttpAbort, _Mapping]] = ..., heartbeat: _Optional[_Union[_utils_pb2.Heartbeat, _Mapping]] = ...) -> None: ...
