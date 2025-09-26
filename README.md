
# TianGong AI Unstructure Serve

## Env Preparing

Setup `venv`:

```bash

sudo apt-get install python3.12-dev
sudo apt-get install nvidia-cuda-toolkit

python3.12 -m venv .venv
source .venv/bin/activate
```

Install requirements:

```bash
python.exe -m pip install --upgrade pip

pip install --upgrade pip

pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install -r requirements.txt --upgrade

pip install -r requirements_freeze.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

pip install torch==2.8 torchvision torchaudio -i https://pypi.tuna.tsinghua.edu.cn/simple
  

wget https://gcore.jsdelivr.net/gh/opendatalab/MinerU@master/scripts/download_models_hf.py -O download_models_hf.py
python download_models_hf.py

pip freeze > requirements_freeze.txt
```

Auto lint:
```bash
pip install black
black .
```

```bash
sudo apt update

sudo apt install -y libmagic-dev
sudo apt install -y poppler-utils
sudo apt install -y libreoffice
sudo apt install -y pandoc
sudo apt install -y graphicsmagick
```

Test Cuda (optional):

```bash
watch -n 1 nvidia-smi
```

Start Server:

```bash



MINERU_MODEL_SOURCE=modelscope TABLE_OCR=paddle OCR_AGENT=unstructured.partition.utils.ocr_models.paddle_ocr.OCRAgentPaddle uvicorn src.main:app --host 0.0.0.0 --port 7770

MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=0 OCR_AGENT=unstructured.partition.utils.ocr_models.paddle_ocr.OCRAgentPaddle uvicorn src.main:app --host 0.0.0.0 --port 8770
MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=1 OCR_AGENT=unstructured.partition.utils.ocr_models.paddle_ocr.OCRAgentPaddle uvicorn src.main:app --host 0.0.0.0 --port 8771
MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=2 OCR_AGENT=unstructured.partition.utils.ocr_models.paddle_ocr.OCRAgentPaddle uvicorn src.main:app --host 0.0.0.0 --port 8772

# run in background

nohup env MINERU_MODEL_SOURCE=modelscope TABLE_OCR=paddle OCR_AGENT=unstructured.partition.utils.ocr_models.paddle_ocr.OCRAgentPaddle uvicorn src.main:app --host 0.0.0.0 --port 7770 > uvicorn.log 2>&1 &

nohup env MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=0 TABLE_OCR=paddle OCR_AGENT=unstructured.partition.utils.ocr_models.paddle_ocr.OCRAgentPaddle uvicorn src.main:app --host 0.0.0.0 --port 8770 > uvicorn.log 2>&1 &
nohup env MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=1 TABLE_OCR=paddle OCR_AGENT=unstructured.partition.utils.ocr_models.paddle_ocr.OCRAgentPaddle uvicorn src.main:app --host 0.0.0.0 --port 8771 > uvicorn.log 2>&1 &
nohup env MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=2 TABLE_OCR=paddle OCR_AGENT=unstructured.partition.utils.ocr_models.paddle_ocr.OCRAgentPaddle uvicorn src.main:app --host 0.0.0.0 --port 8772 > uvicorn.log 2>&1 &

npm i -g pm2

pm2 start ecosystem.config.json

pm2 start ecosystem.quatro.json

pm2 restart all

pm2 status

pm2 restart unstructured-gunicorn
pm2 stop unstructured-gunicorn
pm2 delete unstructured-gunicorn

pm2 logs unstructured-gunicorn

pm2 delete all

# 使用 for 循环和 lsof
for port in {8770..8773}
do
  # lsof -t 选项只会输出PID，方便后续处理
  PID=$(sudo lsof -t -i:$port)
  
  if [ -n "$PID" ]; then
    echo "找到占用端口 $port 的进程，PID: $PID。正在终止..."
    sudo kill -9 $PID
  else
    echo "端口 $port 未被占用。"
  fi
done

# 使用 lsof 清理 7770 端口
port=7770
# lsof -t 选项只会输出PID，方便后续处理
PID=$(sudo lsof -t -i:$port)

if [ -n "$PID" ]; then
  echo "找到占用端口 $port 的进程，PID: $PID。正在终止..."
  sudo kill -9 $PID
else
  echo "端口 $port 未被占用。"
fi

```
