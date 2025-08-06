@echo off
setlocal EnableExtensions

rem === 路径 ===
set "WORKER_DIR=D:\ComfyUI_Worker"
set "COMFYUI_DIR=D:\ComfyUI-aki\ComfyUI"
set "PYTHON_EXE=D:\ComfyUI-aki\python\python.exe"

rem === 仅对本次脚本生效的环境变量 ===
set "PYTHONPATH=%COMFYUI_DIR%"
set "HF_ENDPOINT=https://hf-mirror.com"
set "CUDA_VISIBLE_DEVICES=0"
set "TASKQ_SERVER_URL=quickposer.com:10087"
@REM 默认可以填win32-group1
set "TASKQ_WORKER_GROUP=win32-group1"
@REM 登录你的租户账户后创建token, 替换之                      
set "TASKQ_ACCESS_KEY=qp_dqdwibYY3VjHeELNqoyDAMxqBaFgO4d6463vkvud"

rem 如果系统已设置 CUDA_PATH，则把其 bin 加到 PATH（供 DLL 搜索）
if defined CUDA_PATH (
  set "CUDA_HOME=%CUDA_PATH%"
  set "PATH=%CUDA_HOME%\bin;%PATH%"
)

rem === 进入工作目录并启动（输出直接打印到当前控制台）===
pushd "%WORKER_DIR%"
"%PYTHON_EXE%" -u main.py --port 8188 --disable-metadata
popd  

endlocal
