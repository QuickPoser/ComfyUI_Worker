import json
import logging
import time
import queue
import asyncio
import traceback
import sys

from concurrent.futures import ThreadPoolExecutor

import env
import grpc

from comfygw_proto import taskq_pb2, taskq_pb2_grpc, utils_pb2

def full_type_name(klass):
    module = klass.__module__
    if module == 'builtins':
        return klass.__qualname__
    return module + '.' + klass.__qualname__

class TaskCancel(Exception):
    pass

class TaskQ(object):
    def __init__(self, server_url, info="", group="", on_cancel_task=None):
        self.server_url = server_url
        self.tasks = {}
        self.info = info
        self.group = group
        self.on_cancel_task = on_cancel_task
        self.loop = None

    def task(self, bind=True):
        def wrapper(func):
            if func.__name__ in self.tasks:
                raise RuntimeError("task name is already registered")

            self.tasks[func.__name__] = TaskFunc(func, bind=bind)
            return func

        return wrapper

    @property
    def task_names(self):
        return self.tasks.keys()

    def on_task(self, worker_session, task_info: taskq_pb2.TaskInfo):
        func_name = task_info.taskName
        args = task_info.args

        err = None
        ret = None
        try:
            dict_args = json.loads(args)
            task_func = self.tasks.get(func_name)
            if task_func is None:
                raise RuntimeError(f"Task '{func_name}' not found")
            logging.info(f"[TaskQ] Start task: {func_name} args: {short_string(args)}")
            asyncio.set_event_loop(self.loop)
            ret = asyncio.run(task_func.call(worker_session, dict_args))
        except TaskCancel as e:
            logging.info(f"[TaskQ] Task '{func_name}' canceled: {e}")
            raise e
        except Exception as ex:
            logging.exception(f"[TaskQ] Exception in task '{func_name}': {ex}")

            typ, _, tb = sys.exc_info()
            exception_type = full_type_name(typ)
            err = {
                "exception_message": "{}".format(ex),
                "exception_type": exception_type,
                "traceback": traceback.format_tb(tb),
            }

        logging.info(f"[TaskQ] End task: {func_name} result: {short_string(str(ret))} error: {err}")
        return ret, err

    def cancel_task(self, task_id):
        logging.info(f"[TaskQ] Cancel task: {task_id}")
        self.on_cancel_task(task_id)

    def run(self, loop: asyncio.AbstractEventLoop = None):
        self.loop = loop        
        while True:
            worker_session = WorkerSession(self)
            try:
                worker_session.run()
            except Exception as e:
                msg = str(e).lower()
                if "socket closed" in msg or "failed to connect" in msg:
                    logging.error(f"[TaskQ] Worker session end: {e}")
                else:
                    logging.exception(f"[TaskQ] Worker session exception: {e}")
            finally:
                worker_session.close()
                logging.info("[TaskQ] Worker session closed, restarting in 5 seconds...")
                time.sleep(5)


def short_string(s, max_len=512):
    if isinstance(s, str) and len(s) > max_len:
        return s[:max_len] + "..."
    else:
        return s


class WorkerSession(object):
    def __init__(self, taskq: TaskQ):
        self.taskq = taskq
        self._send_queue = queue.Queue()
        self.current_task_id = None
        self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="TaskQWorker")
        self._closed = False

    def send_message(self, **kwargs):
        if not self._closed:
            self._send_queue.put(taskq_pb2.WorkerMessage(**kwargs))

    def _message_generator(self):
        heartbeat_interval = 10
        last_heartbeat = time.time()
        while True:
            try:
                timeout = max(0, heartbeat_interval - (time.time() - last_heartbeat))
                msg = self._send_queue.get(timeout=timeout)
                if msg is None:
                    logging.info("[WorkerSession] Message generator received close signal.")
                    break
                yield msg
            except queue.Empty:
                if self._closed:
                    logging.info("[WorkerSession] Message generator closed on heartbeat timeout.")
                    break
                yield taskq_pb2.WorkerMessage(heartbeat=utils_pb2.Heartbeat())
                last_heartbeat = time.time()
            if self._closed and self._send_queue.empty():
                logging.info("[WorkerSession] Message generator exiting (closed and empty).")
                break

    def progress(self, progress):
        if self.current_task_id is None:
            return
        
        self.send_message(
            progress=taskq_pb2.TaskProgress(
                taskId=self.current_task_id,
                progress=str(progress),
            )
        )

    def run(self):
        with grpc.insecure_channel(self.taskq.server_url) as grpc_channel:
            stub = taskq_pb2_grpc.TaskServiceStub(grpc_channel)
            stream = stub.BeginWork(self._message_generator())
            self.send_message(
                auth=utils_pb2.AuthReq(
                    accessToken=env.taskq_access_key,
                    sessionId=env.session_id,
                    hostName=env.hostname,
                    info=self.taskq.info,
                    group=self.taskq.group,
                    acceptTasks=self.taskq.task_names,
                )
            )

            broker_msg: taskq_pb2.BrokerMessage = next(stream)
            auth_rsp = broker_msg.authRsp
            if auth_rsp is None:
                raise RuntimeError("register failed")
            
            if not auth_rsp.ok:
                raise RuntimeError(f"register failed: {auth_rsp.errorMsg}")

            logging.info("[WorkerSession] Register success")
            try:
                self.send_message(ready=taskq_pb2.WorkerReady())
                for msg in stream:
                    if isinstance(msg, taskq_pb2.BrokerMessage):
                        if msg.HasField("taskInfo"):
                            if self.current_task_id is not None:
                                raise RuntimeError("current task is not None")
                            task_info = msg.taskInfo
                            self.current_task_id = task_info.taskId
                            logging.info(f"[WorkerSession] Received task: {task_info.taskName} id: {task_info.taskId}")
                            self.executor.submit(self.run_task, task_info)
                        elif msg.HasField("cancelTask"):
                            cancel_info = msg.cancelTask
                            if self.current_task_id == cancel_info.taskId:
                                logging.info(f"[WorkerSession] Received cancel for task: {cancel_info.taskId}")
                                self.executor.submit(
                                    self.cancel_task, cancel_info.taskId
                                )
            except Exception as e:
                logging.exception(f"[WorkerSession] Exception in run: {e}")
                raise e
            finally:
                self.close()

    def run_task(self, task_info):
        try:
            task_id = task_info.taskId
            logging.info(
                f"[WorkerSession] Task {task_id} start, taskName: {task_info.taskName} args: {short_string(task_info.args)}"
            )
            ret, err = self.taskq.on_task(self, task_info)
            result = taskq_pb2.TaskResult(
                taskId=task_id,
                code=0 if err is None else 1,
                error=json.dumps(err),
                result=json.dumps(ret),
            )
            logging.info(f"[WorkerSession] Task {task_id} end, result: {short_string(str(result))}")
            self.current_task_id = None
            self.send_message(result=result)
            self.send_message(ready=taskq_pb2.WorkerReady())
        except TaskCancel:
            logging.info(f"[WorkerSession] Task {task_id} canceled")
            self.current_task_id = None
            cancel = taskq_pb2.TaskCancel(taskId=task_id)
            self.send_message(cancel=cancel)
            self.send_message(ready=taskq_pb2.WorkerReady())
        except Exception as e:
            logging.exception(f"[WorkerSession] Exception in run_task: {e}")
            raise e

    def cancel_task(self, task_id):
        if self.current_task_id == task_id:
            logging.info(f"[WorkerSession] Cancel task: {task_id}")
            self.taskq.cancel_task(task_id)

    def close(self):
        self._closed = True
        logging.info("[WorkerSession] Closing session")
        # 立即唤醒阻塞的 get
        self._send_queue.put(None)
        if self.current_task_id is not None:
            self.taskq.cancel_task(self.current_task_id)
        self.executor.shutdown(wait=False)


class TaskFunc(object):
    def __init__(self, func, bind=True):
        self.func = func
        self.bind = bind

    def call(self, bind_arg, dict_args):
        if not self.bind:
            return self.func(**dict_args)
        else:
            return self.func(bind_arg, **dict_args)
