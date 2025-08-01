import utils_pb2 as _utils_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class WorkerReady(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class TaskProgress(_message.Message):
    __slots__ = ["taskId", "progress"]
    TASKID_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    taskId: str
    progress: str
    def __init__(self, taskId: _Optional[str] = ..., progress: _Optional[str] = ...) -> None: ...

class TaskResult(_message.Message):
    __slots__ = ["taskId", "code", "result", "error"]
    TASKID_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    taskId: str
    code: int
    result: str
    error: str
    def __init__(self, taskId: _Optional[str] = ..., code: _Optional[int] = ..., result: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class TaskCancel(_message.Message):
    __slots__ = ["taskId"]
    TASKID_FIELD_NUMBER: _ClassVar[int]
    taskId: str
    def __init__(self, taskId: _Optional[str] = ...) -> None: ...

class WorkerMessage(_message.Message):
    __slots__ = ["auth", "ready", "heartbeat", "progress", "result", "cancel"]
    AUTH_FIELD_NUMBER: _ClassVar[int]
    READY_FIELD_NUMBER: _ClassVar[int]
    HEARTBEAT_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    CANCEL_FIELD_NUMBER: _ClassVar[int]
    auth: _utils_pb2.AuthReq
    ready: WorkerReady
    heartbeat: _utils_pb2.Heartbeat
    progress: TaskProgress
    result: TaskResult
    cancel: TaskCancel
    def __init__(self, auth: _Optional[_Union[_utils_pb2.AuthReq, _Mapping]] = ..., ready: _Optional[_Union[WorkerReady, _Mapping]] = ..., heartbeat: _Optional[_Union[_utils_pb2.Heartbeat, _Mapping]] = ..., progress: _Optional[_Union[TaskProgress, _Mapping]] = ..., result: _Optional[_Union[TaskResult, _Mapping]] = ..., cancel: _Optional[_Union[TaskCancel, _Mapping]] = ...) -> None: ...

class TaskInfo(_message.Message):
    __slots__ = ["taskId", "taskName", "args"]
    TASKID_FIELD_NUMBER: _ClassVar[int]
    TASKNAME_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    taskId: str
    taskName: str
    args: str
    def __init__(self, taskId: _Optional[str] = ..., taskName: _Optional[str] = ..., args: _Optional[str] = ...) -> None: ...

class CancelTask(_message.Message):
    __slots__ = ["taskId"]
    TASKID_FIELD_NUMBER: _ClassVar[int]
    taskId: str
    def __init__(self, taskId: _Optional[str] = ...) -> None: ...

class BrokerMessage(_message.Message):
    __slots__ = ["authRsp", "taskInfo", "cancelTask"]
    AUTHRSP_FIELD_NUMBER: _ClassVar[int]
    TASKINFO_FIELD_NUMBER: _ClassVar[int]
    CANCELTASK_FIELD_NUMBER: _ClassVar[int]
    authRsp: _utils_pb2.AuthRsp
    taskInfo: TaskInfo
    cancelTask: CancelTask
    def __init__(self, authRsp: _Optional[_Union[_utils_pb2.AuthRsp, _Mapping]] = ..., taskInfo: _Optional[_Union[TaskInfo, _Mapping]] = ..., cancelTask: _Optional[_Union[CancelTask, _Mapping]] = ...) -> None: ...

class DownloadRequest(_message.Message):
    __slots__ = ["fileID"]
    FILEID_FIELD_NUMBER: _ClassVar[int]
    fileID: str
    def __init__(self, fileID: _Optional[str] = ...) -> None: ...

class DownloadResponse(_message.Message):
    __slots__ = ["chunk"]
    CHUNK_FIELD_NUMBER: _ClassVar[int]
    chunk: bytes
    def __init__(self, chunk: _Optional[bytes] = ...) -> None: ...

class UploadRequest(_message.Message):
    __slots__ = ["chunk"]
    CHUNK_FIELD_NUMBER: _ClassVar[int]
    chunk: bytes
    def __init__(self, chunk: _Optional[bytes] = ...) -> None: ...

class UploadResponse(_message.Message):
    __slots__ = ["fileID"]
    FILEID_FIELD_NUMBER: _ClassVar[int]
    fileID: str
    def __init__(self, fileID: _Optional[str] = ...) -> None: ...
