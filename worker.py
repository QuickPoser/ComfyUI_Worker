import env
import asyncio
import torch
import sys
import json
import time
import gc
import nodes

from taskq import TaskQ, WorkerSession, TaskCancel
import execution
from execution import ExecutionResult, IsChangedCache, IsChangedCache, execute
import comfy.model_management
from comfy_execution.graph import ExecutionList, DynamicPrompt
from comfy_execution.progress import reset_progress_state, add_progress_handler, WebUIProgressHandler
from comfy.cli_args import args

def get_info():
    import os
    try:
        import comfyui_version
        comfyui_version = comfyui_version.__version__
    except ImportError:
        comfyui_version = "unknown"
    info = {
        "envrions": {key: value for key, value in os.environ.items()},
        "command_line": sys.executable + " " + " ".join(sys.argv),
        "comfyui_version": comfyui_version,
        "worker_version": "0.3.49",
    }
    return json.dumps(info)


executor = None
task_context = None
gc_collect_interval = 10.
last_gc_collect = 0

def on_cancel_task(task_id):
    global task_context
    if task_context is not None:
        if task_context.task_id == task_id:            
            nodes.interrupt_processing(True)

taskq = TaskQ(
    env.taskq_server_url, 
    info=get_info(), 
    group=env.taskq_group, 
    on_cancel_task=on_cancel_task
)

origin_get_input_data = execution.get_input_data

def get_input_data(inputs, class_def, unique_id, outputs=None, dynprompt=None, extra_data={}):
    global task_context
    result = origin_get_input_data(inputs, class_def, unique_id, outputs, dynprompt, extra_data)
    input_data_all = result[0]

    valid_inputs = class_def.INPUT_TYPES()
    if "hidden" in valid_inputs:
        h = valid_inputs["hidden"]
        for x in h:
            if h[x] == "TASK_CONTEXT":
                input_data_all[x] = [task_context]

    return result

execution.get_input_data = get_input_data

class TaskContext:
    def __init__(self, session: WorkerSession, context):
        self.task_id = session.current_task_id
        self.session = session
        self.context = context

    def progress(self, event, data):
        self.session.progress(json.dumps({"type": event, "data": data}))

    def json(self):
        return json.dumps({"task_id": self.task_id, "context": self.context})

    def __repr__(self):
        return f"TaskContext(task_id={self.task_id}, session={self.session}, context={self.context})"

class PromptExecutor(execution.PromptExecutor):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_execute_error = None

    def handle_execution_error(self, prompt_id, prompt, current_outputs, executed, error, ex):
        super().handle_execution_error(prompt_id, prompt, current_outputs, executed, error, ex)
        self.last_execute_error = {
            "prompt_id": prompt_id,
            "prompt": prompt,
            "current_outputs": current_outputs,
            "executed": executed,
            "error": error,
            "exception": ex
        }

    async def execute_async(self, prompt, prompt_id, extra_data={}, execute_outputs=[], client_id=None):        
        self.last_execute_error = None
        self.history_result = {}
        extra_data["client_id"] = client_id

        await super().execute_async(prompt, prompt_id, extra_data=extra_data, execute_outputs=execute_outputs)

        execute_error = self.last_execute_error
        ui_outputs = self.history_result.get("outputs", None)
        meta_outputs = self.history_result.get("meta_outputs", None)
        return (ui_outputs, meta_outputs, execute_error)

@taskq.task()
async def comfy_execute_prompt(session: WorkerSession, prompt: object, extra_data: object, context: object, client_id=None, **kwargs):
    global task_context, last_gc_collect

    valid, err, outputs_to_execute, node_errors = await execution.validate_prompt(session.current_task_id, prompt, None)
    if not valid or len(node_errors) > 0:
        return {
            "status": "validation_error",
            "error": err or {
                "type": "validation_error",
                "message": "Prompt validation failed.",
                "details": "The prompt is not valid or has errors.",
            },
            "node_errors": node_errors
        }

    task_context = TaskContext(session, context=context)

    # 某些情况下节点会改变 default dtype, 我们需要重置为 float32
    torch.set_default_dtype(torch.float32)

    executor.server.last_prompt_id = task_context.task_id
    executor.server.set_current_session(session)
    
    prompt_id = task_context.task_id

    ui_outputs, meta_outputs, execute_error = await executor.execute_async(
        prompt, prompt_id, extra_data, outputs_to_execute, client_id
    )
    executor.server.send_sync(
        "executing", {"node": None, "prompt_id": prompt_id}
    )

    executor.server.set_current_session(None)
    executor.server.client_id = None

    current_time = time.perf_counter()
    if (current_time - last_gc_collect) > gc_collect_interval:
        gc.collect()
        comfy.model_management.soft_empty_cache()
        last_gc_collect = current_time

    task_context = None
    if execute_error is not None:
        if isinstance(
            execute_error['exception'], 
            comfy.model_management.InterruptProcessingException
        ):
            raise TaskCancel()
        
        ret = {
            "status": "execution_error",
            "error": execute_error['error'],
        }
    else:
        ret = ui_outputs        
    
    return ret


def run(server, loop: asyncio.AbstractEventLoop):
    global executor
    executor = PromptExecutor(server, cache_type=execution.CacheType.LRU, cache_size=args.cache_lru)
    taskq.run(loop)