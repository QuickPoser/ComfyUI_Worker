#!/bin/bash

# 激活虚拟环境, 如果当前环境已经完整体Python环境, 则无需激活
# e,g: 如仙宫云默认就是conda环境, 这此处无需激活
source venv/bin/activate

# 设置环境变量
export WORKER_DIR=/root/ComfyUI_Worker    # 填写你ComfyUI_Worker所在目录
export PYTHONPATH=/root/ComfyUI           # 填写你ComfyUI所在目录
export CUDA_HOME=/usr/local/cuda          # 填写你CUDA目录
export PATH=/usr/local/cuda/bin:$PATH     # 填写你CUDA所在PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH  # 填写你CUDA所在LD_LIBRARY_PATH
export HF_ENDPOINT=https://hf-mirror.com
export TASKQ_SERVER_URL=quickposer.com:10087
export TASKQ_ACCESS_KEY=<你的租户token>              # 登录你的租户账户后创建
export TASKQ_WORKER_GROUP=<你自定义的workgroup名字>  # 默认可以填group1

# 当有多张GPU卡的时候，可以通过此方式来指定使用的GPU
export CUDA_VISIBLE_DEVICES=0
# export CUDA_VISIBLE_DEVICES=1

# 切换到指定目录并启动Python服务
cd $WORKER_DIR && python main.py --listen --port 8188 --disable-metadata
