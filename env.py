import environs
import sys
import os
import uuid
import platform

taskq_server_url = os.getenv("TASKQ_SERVER_URL", "127.0.0.1:10086")
taskq_group = os.getenv("TASKQ_WORKER_GROUP", "")
taskq_access_key = os.getenv("TASKQ_ACCESS_KEY", "")
session_id = uuid.uuid4().hex
hostname = f"{os.getpid()}@{platform.node()}"

COMFY_PATH = os.getenv("PYTHONPATH", None) 
if COMFY_PATH is None:        
    env = environs.Env()
    env.read_env()
    COMFY_PATH = env("PYTHONPATH")

if COMFY_PATH:    
    base_path = os.path.dirname(__file__)
    sys.path.append(base_path)
    sys.path.append(COMFY_PATH)
    
    # change current working directory to COMFY_PATH
    # os.chdir(COMFY_PATH)
else:
    sys.exit("PYTHONPATH not set")

# Just a magic line to make sure the module is imported
import importlib.util
module_spec = importlib.util.find_spec("utils.json_util")
if module_spec is None:
    sys.exit("Module utils.json_util not found! Check sys.path and package structure.")
