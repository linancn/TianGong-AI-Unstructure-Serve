
# TianGong AI Unstructure Serve

## Env Preparing

Use [uv](https://docs.astral.sh/uv/) to manage Python and project dependencies:

```bash
# (optional) install uv if it is not available yet
curl -LsSf https://astral.sh/uv/install.sh | sh

# ensure CPython 3.12 is available locally
uv python install 3.12

# install all project dependencies into .venv/
uv sync
```

`uv sync` reads `pyproject.toml` (and `uv.lock` when present) to create a virtual environment at `.venv/`.  
All runtime and development dependencies now live in `pyproject.toml`; the legacy requirement files are retained only for reference.
Activate it with `source .venv/bin/activate` or prefer `uv run …` / `uv venv` for ephemeral shells.

Download MinerU models (first run only):

```bash
wget https://gcore.jsdelivr.net/gh/opendatalab/MinerU@master/scripts/download_models_hf.py -O download_models_hf.py
uv run python download_models_hf.py
```

### Development helpers

```bash
uv run --group dev black .
uv run --group dev ruff check src
uv run --group dev pytest
```

```bash
sudo apt update

sudo apt install -y libmagic-dev
sudo apt install -y poppler-utils
sudo apt install -y libreoffice
sudo apt install -y pandoc
sudo apt install -y graphicsmagick
```

### MinerU runtime defaults (.env)

- `.env` is loaded automatically; adjust defaults there without touching code.
- `MINERU_DEFAULT_BACKEND` controls the parsing backend (default `vlm-http-client`; options: `pipeline`, `vlm-transformers`, `vlm-vllm-engine`, `vlm-lmdeploy-engine`, `vlm-http-client`, `vlm-mlx-engine`).
- `MINERU_DEFAULT_LANG` sets the OCR language hint for pipeline mode (default `ch`).
- `MINERU_DEFAULT_METHOD` sets the pipeline parse method (`auto`/`txt`/`ocr`, default `auto`).
- `MINERU_VLLM_SERVER_URLS` / `MINERU_VLLM_SERVER_URL` (or `MINERU_VLM_SERVER_URLS` / `MINERU_VLM_SERVER_URL`) list VLM endpoints; comma-separated or JSON array values are accepted. If unset, the service falls back to `http://127.0.0.1:30000`.

Test Cuda (optional):

```bash
watch -n 1 nvidia-smi
```

Start Server:

```bash
# run from within the uv-managed environment (activate .venv or prefix with `uv run`)
MINERU_MODEL_SOURCE=modelscope uvicorn src.main:app --host 0.0.0.0 --port 7770

MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=0 uvicorn src.main:app --host 0.0.0.0 --port 8770
MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=1 uvicorn src.main:app --host 0.0.0.0 --port 8771
MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=2 uvicorn src.main:app --host 0.0.0.0 --port 8772

# run in background

nohup env MINERU_MODEL_SOURCE=modelscope uvicorn src.main:app --host 0.0.0.0 --port 7770 > uvicorn.log 2>&1 &

nohup env MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=0 uvicorn src.main:app --host 0.0.0.0 --port 8770 > uvicorn.log 2>&1 &
nohup env MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=1 uvicorn src.main:app --host 0.0.0.0 --port 8771 > uvicorn.log 2>&1 &
nohup env MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=2 uvicorn src.main:app --host 0.0.0.0 --port 8772 > uvicorn.log 2>&1 &

npm i -g pm2

pm2 start ecosystem.vllm.config.json
pm2 start ecosystem.config.json

pm2 start ecosystem.vllm.quatro.json
pm2 start ecosystem.quatro.json

pm2 restart all

pm2 status

pm2 restart all

pm2 status

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

# Kroki Server
```bash
docker run -d -p --restart unless-stopped 7999:8000 yuzutech/kroki
```
# Quickchart Server
```bash
docker run -d -p --restart unless-stopped 7998:3400 ianw/quickchart
```

# MinIO Server
```bash
docker run -d \
  -p 9000:9000 \
  -p 9001:9001 \
  --name minio \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=yourpassword \
  --restart unless-stopped \
  -v "$(pwd)/minio/data:/data" \
  quay.io/minio/minio server /data --console-address ":9001"

```

# MinerU vLLM Server
```bash
# Run first time to download models
MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=0 mineru-vllm-server --port 30000
```
