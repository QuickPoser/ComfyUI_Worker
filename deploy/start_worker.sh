#!/bin/bash

# 激活虚拟环境, 如果当前环境已经玩整体Python环境, 则无需激活
source venv/bin/activate

# 设置环境变量
export WORKER_DIR=/root/ComfyUI_Worker    # 填写你ComfyUI_Worker所在目录
export PYTHONPATH=/root/ComfyUI           # 填写你ComfyUI所在目录
export PATH=/usr/local/cuda-12.8/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda-12.8/lib64:$LD_LIBRARY_PATH
export CUDA_HOME=/usr/local/cuda-12.8
export HF_ENDPOINT=https://hf-mirror.com

# 当有多张GPU卡的时候，可以通过此方式来指定使用的GPU
export CUDA_VISIBLE_DEVICES=0
# export CUDA_VISIBLE_DEVICES=1

# 切换到指定目录并启动Python服务
cd $WORKER_DIR && python main.py --listen --port 8188 --disable-metadata
