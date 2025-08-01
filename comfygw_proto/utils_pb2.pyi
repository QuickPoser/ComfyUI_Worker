from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class Heartbeat(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class AuthReq(_message.Message):
    __slots__ = ["sessionId", "accessToken", "group", "hostName", "info", "acceptTasks"]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    ACCESSTOKEN_FIELD_NUMBER: _ClassVar[int]
    GROUP_FIELD_NUMBER: _ClassVar[int]
    HOSTNAME_FIELD_NUMBER: _ClassVar[int]
    INFO_FIELD_NUMBER: _ClassVar[int]
    ACCEPTTASKS_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    accessToken: str
    group: str
    hostName: str
    info: str
    acceptTasks: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, sessionId: _Optional[str] = ..., accessToken: _Optional[str] = ..., group: _Optional[str] = ..., hostName: _Optional[str] = ..., info: _Optional[str] = ..., acceptTasks: _Optional[_Iterable[str]] = ...) -> None: ...

class AuthRsp(_message.Message):
    __slots__ = ["ok", "errorMsg"]
    OK_FIELD_NUMBER: _ClassVar[int]
    ERRORMSG_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    errorMsg: str
    def __init__(self, ok: bool = ..., errorMsg: _Optional[str] = ...) -> None: ...
