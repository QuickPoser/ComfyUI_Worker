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
    info = {
        "envrions": {key: value for key, value in os.environ.items()},
        "command_line": sys.executable + " " + " ".join(sys.argv),
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
    input_data_all, missing_keys = origin_get_input_data(inputs, class_def, unique_id, outputs, dynprompt, extra_data)

    valid_inputs = class_def.INPUT_TYPES()
    if "hidden" in valid_inputs:
        h = valid_inputs["hidden"]
        for x in h:
            if h[x] == "TASK_CONTEXT":
                input_data_all[x] = [task_context]

    return input_data_all, missing_keys

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
        self.context = None

    async def execute_async(self, prompt, prompt_id, extra_data={}, execute_outputs=[], client_id=None):
        nodes.interrupt_processing(False)

        self.server.set_current_session(task_context.session)
        self.server.client_id = client_id

        self.status_messages = []
        self.add_message("execution_start", { "prompt_id": prompt_id}, broadcast=False)

        with torch.inference_mode():
            dynamic_prompt = DynamicPrompt(prompt)
            reset_progress_state(prompt_id, dynamic_prompt)
            add_progress_handler(WebUIProgressHandler(self.server))
            is_changed_cache = IsChangedCache(prompt_id, dynamic_prompt, self.caches.outputs)
            for cache in self.caches.all:
                await cache.set_prompt(dynamic_prompt, prompt.keys(), is_changed_cache)
                cache.clean_unused()

            cached_nodes = []
            for node_id in prompt:
                if self.caches.outputs.get(node_id) is not None:
                    cached_nodes.append(node_id)

            comfy.model_management.cleanup_models_gc()
            self.add_message("execution_cached",
                          { "nodes": cached_nodes, "prompt_id": prompt_id},
                          broadcast=False)
            pending_subgraph_results = {}
            pending_async_nodes = {} # TODO - Unify this with pending_subgraph_results
            executed = set()
            execution_list = ExecutionList(dynamic_prompt, self.caches.outputs)
            current_outputs = self.caches.outputs.all_node_ids()
            for node_id in list(execute_outputs):
                execution_list.add_node(node_id)

            exuecute_error = None
            while not execution_list.is_empty():
                node_id, error, ex = await execution_list.stage_node_execution()
                if error is not None:
                    self.handle_execution_error(prompt_id, dynamic_prompt.original_prompt, current_outputs, executed, error, ex)
                    break

                assert node_id is not None, "Node ID should not be None at this point"
                result, error, ex = await execute(self.server, dynamic_prompt, self.caches, node_id, extra_data, executed, prompt_id, execution_list, pending_subgraph_results, pending_async_nodes)
                self.success = result != ExecutionResult.FAILURE
                if result == ExecutionResult.FAILURE:
                    self.handle_execution_error(prompt_id, dynamic_prompt.original_prompt, current_outputs, executed, error, ex)
                    exuecute_error = {
                        "node_id": node_id,
                        "error": error,
                        "exception": ex
                    }

                    break
                elif result == ExecutionResult.PENDING:
                    execution_list.unstage_node_execution()
                else: # result == ExecutionResult.SUCCESS:
                    execution_list.complete_node_execution()
            else:
                # Only execute when the while-loop ends without break
                self.add_message("execution_success", { "prompt_id": prompt_id }, broadcast=False)

            ui_outputs = {}
            meta_outputs = {}
            all_node_ids = self.caches.ui.all_node_ids()
            for node_id in all_node_ids:
                ui_info = self.caches.ui.get(node_id)
                if ui_info is not None:
                    ui_outputs[node_id] = ui_info["output"]
                    meta_outputs[node_id] = ui_info["meta"]
            self.history_result = {
                "outputs": ui_outputs,
                "meta": meta_outputs,
            }
            self.server.last_node_id = None
            if comfy.model_management.DISABLE_SMART_MEMORY:
                comfy.model_management.unload_all_models()

            return (ui_outputs, meta_outputs, exuecute_error)

@taskq.task()
async def comfy_execute_prompt(session: WorkerSession, prompt: object, extra_data: object, context: object, client_id=None, **kwargs):
    global task_context, last_gc_collect

    valid, err, outputs_to_execute, node_errors = await execution.validate_prompt(session.current_task_id, prompt)
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
    
    ui_outputs, meta_outputs, execute_error = await executor.execute_async(
        prompt, task_context.task_id, extra_data, outputs_to_execute, client_id=client_id
    )

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