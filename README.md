# **ComfyUI\_Worker - 闪报 (QuickPoser) 代理客户端**

`ComfyUI_Worker` 是一个为 **闪报 (QuickPoser)** 平台设计的代理客户端。它的核心功能是接收和路由来自云端的租户分发任务，让您能够将本地的 ComfyUI 计算能力安全、高效地接入闪报平台。

-----

## **⚠️ 重要提示：服务开通**

请注意，`ComfyUI_Worker` 仅仅是一个连接到云端服务的客户端。**要使其正常工作，您必须首先联系闪报工作人员为您开通云端租户账户。**

  * **开通方式：** 请添加下方微信号，并向工作人员说明您的需求。
  * **微信号：** `byqin007`
  * **官网：** `https://quickposer.com`

-----

## **安装与部署指南**

在开始之前，请仔细阅读以下部署步骤。

### **一、 环境要求**

1.  **ComfyUI 版本：** 您的 ComfyUI 需要升级到 `v0.3.47` 或更高版本。
2.  **ComfyUI 状态：** 请确保您的 ComfyUI 本体可以独立、正常地启动和运行。
3.  **非侵入式设计：** `ComfyUI_Worker` 不会修改您的 ComfyUI 本体、任何现有插件或模型。所有关于 ComfyUI 的配置，请在原版程序或其启动器中完成。

-----

### **二、 目录结构**

请将下载的 `ComfyUI_Worker` 文件夹放置在您 ComfyUI 的根目录下。以下是两种常见安装方式的目录结构示例：

- 场景一：ComfyUI 官方整合包
```
ComfyUI_windows_portable/
│
├── ComfyUI/                # ComfyUI 本体
├── python_embeded/         # 本体自带的 Python 解释器
│   └── python312._pth      # [重要] 可能需要修改此文件
│
└── ComfyUI_Worker/         # 将代理Worker放置在此处
```

> **💡 提示：** 如果后续步骤遇到模块找不到（Module Not Found）的错误，请打开 `python_embeded` 目录下的 `._pth` 文件（文件名可能因您的Python版本而异），**取消 `import site` 这一行的注释**（即删除行首的 `#`），以允许程序加载通过pip安装的第三方库。并增加配置: ../ComfyUI_Worker

- 场景二：秋叶 ComfyUI 启动器整合包
```
ComfyUI-aki/
│
├── ComfyUI/                # ComfyUI 本体
├── python/                 # 启动器自带的 Python 解释器
└── ComfyUI_Worker/         # 将代理Worker放置在此处
```

-----

### **三、 安装依赖项**

在启动 Worker 之前，需要为其安装必要的 Python 依赖库。请**使用管理员权限**打开命令提示符 (CMD) 或 PowerShell，并根据您的安装方式执行相应命令。

**强烈建议使用绝对路径**来指定 `python.exe` 和 `requirements.txt` 的位置，以避免因路径问题导致安装失败。

```powershell
# 如果您的 Python 环境没有 pip，请先执行此命令安装。
# (请将 "D:\ComfyUI-aki\python" 替换为您的实际 Python 目录)
Invoke-WebRequest -Uri https://bootstrap.pypa.io/get-pip.py -OutFile get-pip.py
D:\ComfyUI-aki\python\python.exe get-pip.py
```

**请根据您的目录结构，选择以下一条命令执行以安装依赖：**

  * **对于 ComfyUI 官方整合包：**

    ```cmd
    D:\ComfyUI_windows_portable\python_embeded\python.exe -m pip install -r D:\ComfyUI_windows_portable\ComfyUI_Worker\requirements.txt
    ```

  * **对于秋叶启动器整合包：**

    ```cmd
    D:\ComfyUI-aki\python\python.exe -m pip install -r D:\ComfyUI-aki\ComfyUI_Worker\requirements.txt
    ```

### **四、 配置启动脚本**

用文本编辑器打开 `ComfyUI_Worker\deploy` 目录下的 `start_worker.bat` 文件，您需要根据实际情况修改以下路径和配置信息。

```batch
@echo off
chcp 65001

:: ========================== ↓↓↓ 请根据您的实际情况修改此区域的配置 ↓↓↓ ==========================

:: 1. 核心路径设置 (请务必使用您的实际绝对路径)
set "WORKER_DIR=D:\ComfyUI_windows_portable\ComfyUI_Worker"
set "COMFYUI_DIR=D:\ComfyUI_windows_portable\ComfyUI"
set "PYTHON_EXE=D:\ComfyUI_windows_portable\python_embeded\python.exe"

:: 2. 闪报平台配置 (由租户管理员提供)
rem 访问密钥，在闪报平台创建后获取
set "TASKQ_ACCESS_KEY=qp_dqdwibYY3VjHeELNqoyDAMxqBaFgO4d6463vkvud"

rem 工作组名称，由租户管理员在闪报平台自定义，用于区分不同的机器组
set "TASKQ_WORKER_GROUP=win32-group1"

rem 任务服务器地址，通常无需修改
set "TASKQ_SERVER_URL=quickposer.com:10087"

:: 3. 高级选项 (按需修改)
rem 指定使用的显卡，0代表第一张卡，1代表第二张，以此类推。多卡可用逗号分隔，如 "0,1"
set "CUDA_VISIBLE_DEVICES=0"

rem Hugging Face 镜像端点，用于在国内加速模型下载，可根据网络情况修改
set "HF_ENDPOINT=https://hf-mirror.com"

:: ========================== ↑↑↑ 请根据您的实际情况修改此区域的配置 ↑↑↑ ==========================

:: --- 脚本环境变量设置 (通常无需修改) ---
set "PYTHONPATH=%COMFYUI_DIR%"

echo.
echo =======================================================
echo               ComfyUI_Worker for QuickPoser
echo =======================================================
echo.
echo [INFO] Worker Directory: %WORKER_DIR%
echo [INFO] ComfyUI Directory: %COMFYUI_DIR%
echo [INFO] Python Executable: %PYTHON_EXE%
echo [INFO] Worker Group: %TASKQ_WORKER_GROUP%
echo.
echo [INFO] Starting Worker...
echo.

pushd %WORKER_DIR%
%PYTHON_EXE% main.py

pause
```

### **五、 启动 Worker**

所有配置完成后，请 **以管理员身份右键运行** `start_worker.bat` 脚本。

如果控制台窗口开始输出日志且没有立即报错退出，说明 Worker 已成功启动并正在尝试连接到闪报平台。