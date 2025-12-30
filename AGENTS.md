# TianGong AI Unstructure Serve 代理说明

## 项目概览
- 这是一个基于 FastAPI 的非结构化文档解析与知识入库服务，负责统一封装 MinerU 文档解析、Markdown 转档、MinIO 对象存储、Weaviate 向量数据库写入以及视觉问答能力。
- 主入口在 `src/main.py`，通过依赖注入决定是否开启 Bearer Token 鉴权，并集中挂载各类路由（健康检查、GPU 调度、MinerU 解析、Markdown 转 DOCX、MinIO 上传下载、Weaviate 入库等）。
- GPU 解析任务由自研调度器 `src/services/gpu_scheduler.py` 进行统一排队、超时控制和多进程执行，保障 MinerU 解析稳定性。
- 视觉模型封装在 `src/services/vision_service.py`，按环境变量动态选择 OpenAI、Gemini 或 vLLM 服务，并对模型列表、默认模型及凭证做运行时校验；OpenAI 与 vLLM 通过 `src/services/vision_service_openai_compatible.py` 复用同一套 OpenAI-compatible 客户端池，提示词生成集中在 `src/services/vision_prompts.py`。
- `src/main.py` 初始化根日志记录器为 INFO，并将 `httpx`/`httpcore` 日志级别降至 WARNING，避免打印请求详情。

## 目录速览
- `src/routers/`：各业务路由。`mineru_router.py`/`mineru_sci_router.py`/`mineru_with_images_router.py` 针对不同解析流程，`markdown_router.py` 负责 Markdown→DOCX，`minio_router.py` 负责对象存储操作，`weaviate_router.py` 负责文档入库，`gpu_router.py` 暴露调度状态，`health_router.py` 提供健康检查；`mineru_minio_utils.py` 复用 MinerU 解析的 MinIO 前后处理逻辑。
- `src/services/`：服务层实现。包含 MinerU 解析全流程（含图片/科研版）、Markdown 生成、MinIO 封装、Weaviate 客户端、视觉模型调用及 GPU 调度。
- `src/utils/`：工具函数，例如统一 JSON 响应包装、Markdown 预处理、Office→PDF 转换、MinerU 支持文件扩展名查询、纯文本导出等。
- `src/models/`：Pydantic 数据模型，描述 API 的入参与返回结构（如 `ResponseWithPageNum`（含可选 `txt`/`minio_assets` 字段）、`InsertSummary` 等）。
- `weaviate/`：Weaviate 相关脚本或资源。外部服务容器启动见 README。
- 根目录还包含 `README.md`（环境配置与运维命令）、多个 `ecosystem*.json`（pm2 启动模板）以及 `pyproject.toml`/`uv.lock`（依赖声明）。

## 核心功能
- **MinerU 文档解析**（`src/routers/mineru_router.py` 等）  
  - 支持 PDF、Office、Markdown 等格式，利用 `maybe_convert_to_pdf` 先行格式统一，再调用 GPU 调度器执行 MinerU 管线。  
  - 可选通过 `return_txt` 返回纯文本串（标题段落追加 `\n\n`、普通段落 `\n`）及内容类型标签，结果统一映射到 `TextElementWithPageNum` 模型。
  - 当调用端传入 `chunk_type=true` 时，解析结果除了保留标题（`type="title"`）外，还会额外返回页眉与页脚片段（`type="header"`/`"footer"`），并将页眉放在结果列表顶部；`page_number` 类型仍被忽略，且 `return_txt=true` 时的纯文本输出会按同样顺序拼接。
  - `/mineru` 与 `/mineru_with_images` 均支持 `save_to_minio` 与 `minio_*` 表单字段，成功时会在 `mineru/<文件名>`（可自定义 `minio_prefix`）下写入源 PDF、解析 JSON 与逐页 JPEG，并通过响应体的 `minio_assets` 摘要返回上传结果；当 `chunk_type=true` 时，写入 MinIO 的 `parsed.json` 会保留 `type` 字段（header/footer/title）以便下游消费。两者唯一差异是 `/mineru_with_images` 会额外调用视觉大模型（`pipeline="images"`）为图像生成描述。
  - 额外可选字段 `minio_meta` 会在 `save_to_minio=true` 时把传入字符串写入 `meta.txt`（与 `source.pdf` 同目录），返回的 `minio_assets.meta_object` 会指向该文件，便于下游查阅附加元信息；若 `save_to_minio=false`，后端会安全地忽略该字段，避免调用端因默认值冲突而报错。
  - `mineru_minio_utils.build_minio_prefix()` 支持保留 Unicode/中文字符及常见中文标点，但所有空格（含全角空格）都会被统一替换为 `_`，其余不可打印字符也会折叠为 `_` 并清理多余分隔符；`weaviate_router` 的 `_build_minio_prefix()` 也复用了相同的 `normalize_prefix_component()`，确保 Weaviate 入库场景下的 MinIO 路径规则一致。对应校验见 `tests/test_mineru_minio_utils.py` 与 `tests/test_weaviate_router.py`。
- **Weaviate 入库**（`src/routers/weaviate_router.py`）  
  - 解析流程同 MinerU，并在需要时将 PDF、截图等资产上传至 MinIO（`upload_pdf_bundle`），随后调用 `insert_text_chunks` 将分块文本写入指定 collection。  
  - 支持根据用户与知识库名称生成合法 class 名（`build_weaviate_collection_name`），并可选择视觉模型抽取摘要。
  - `/weaviate/ingest` 与 `/weaviate/ingest_with_images` 提供 `chunk_type` 查询参数（默认 `false`），启用后会保留 MinerU 输出的标题、页眉、页脚分块，并确保这些文本一并写入 Weaviate/MinIO。
- **MinIO 对象操作**（`src/routers/minio_router.py`）  
  - 封装上传/下载所需的 endpoint 解析、bucket 校验与对象名规范化，所有异常以 HTTP 错误返回。  
  - `/minio/upload` 接收标准的 `UploadFile` 表单字段；`/minio/upload/base64` 提供 Base64 版入口（字段 `file_base64`，可选 `content_type_override`），两者共用内置工具完成对象存储写入并在内容为空时返回 400。  
  - 通用配置结构 `MinioConfig` 写在 `src/services/minio_storage.py`。
- **Markdown 工具链**（`src/routers/markdown_router.py` & `src/services/markdown_service.py`）  
  - 允许上传 Markdown 文本和可选的 reference DOCX 模板，将内容转换为 DOCX 并按需清理文档样式（依赖 Pandoc 与 python-docx）。
- **GPU 调度与监控**（`src/services/gpu_scheduler.py`）  
  - 按 GPU ID 创建 `ProcessPoolExecutor`，每个任务在独立子进程执行，并设有硬超时以防解析卡死。  
  - `/gpu/status` 路由可以查询每块 GPU 的排队任务数及运行情况。
- **视觉问答/解析**（`src/services/vision_service.py`）  
  - 统一调度 OpenAI、Gemini、vLLM 视觉大模型；OpenAI 与 vLLM 通过 `vision_service_openai_compatible.py` 共用 OpenAI-compatible 客户端池（支持多个 base_url 轮询），OpenAI 需配置 `OPENAI_API_KEY`，vLLM 使用 `VLLM_BASE_URLS`/`VLLM_BASE_URL`（可逗号分隔）或 `VLLM_API_KEY`。
  - 提示词构建集中在 `vision_prompts.py`，默认文案已明确要求模型直接输出核心洞察，禁止使用“根据您提供的上下文信息”“以下是”等前置客套语。
  - 当 vLLM 仅提供 base_url 而未配置密钥时，会使用占位 key（`not-required`）落到相同的 OpenAI-compatible 请求路径。

## 配置与敏感信息
- 所有默认配置来自 `.secrets/secrets.toml`，通过 `src/config/config.py` 读取；文件顶部会先 `load_dotenv()`，确保 `.env` 环境变量优先级更高（容器/CI 可直接覆盖）。敏感字段包括 FASTAPI Bearer Token、OpenAI/Gemini/VLLM API Key 等。
  - 运行/调试方式：优先在 `.env` 中放敏感值与运行时模型选择；`ecosystem.config.json` 仅用于非敏感覆盖（如超时参数），避免在 PM2 配置中写入密钥或 vLLM base_url。PM2 启动时先加载 `.env`，再应用 `env` 块覆盖同名字段。
- 关键环境变量：  
  - `FASTAPI_AUTH` / `FASTAPI_BEARER_TOKEN` / `FASTAPI_MIDDLEWARE_SECRECT_KEY`：是否开启 Bearer 鉴权及令牌值、中间件密钥。  
  - `MINERU_*`：控制 MinerU 模型源、VLM 服务地址、任务超时时间；新增 `.env` 默认的 MinerU 解析策略：`MINERU_DEFAULT_BACKEND`（默认 `vlm-http-client`，可选 `pipeline`/`vlm-transformers`/`vlm-vllm-engine`/`vlm-lmdeploy-engine`/`vlm-http-client`/`vlm-mlx-engine`）、`MINERU_DEFAULT_LANG`（默认 `ch`）、`MINERU_DEFAULT_METHOD`（默认 `auto`），通过 `python-dotenv` 在解析进程中自动加载。  
  - `MINERU_VLLM_API_KEY` / `MINERU_VLLM_AUTH_HEADER`：为 MinerU `vlm-http-client` 注入 HTTP Authorization 头；优先使用完整的 `MINERU_VLLM_AUTH_HEADER`，否则从 `MINERU_VLLM_API_KEY` 生成 `Bearer <key>`。  
  - `MINERU_OFFICE_CONVERT_TIMEOUT_SECONDS`：LibreOffice Office→PDF 转换超时时间（默认 180s），超时会终止转换并返回 500。  
  - `OPENAI_API_KEY` / `GENIMI_API_KEY`：视觉/生成模型凭证，支持以环境变量覆盖默认 secrets。  
  - `VISION_PROVIDER_CHOICES`、`VISION_MODELS_*`：视觉模型白名单。  
  - `VLLM_BASE_URL` / `VLLM_BASE_URLS` / `VLLM_API_KEY`：指定 vLLM 视觉服务地址/凭证，支持逗号分隔配置多实例，按轮询方式调用（`.secrets/secrets.toml` 支持 `BASE_URL` 与 `BASE_URLS` 两种字段）。  
  - `WEAVIATE_*`：Weaviate 服务地址。  
  - `MINIO_*`：MinIO 凭证与目标桶。  
  - `CUDA_VISIBLE_DEVICES`：运行时显卡绑定。
- 本仓库默认将 `.secrets/` 视为外部私有目录，确保部署前准备好相应文件。

## 环境准备与运行
- 推荐使用 [uv](https://docs.astral.sh/uv/) 管理 Python 3.12 及依赖：`uv python install 3.12` → `uv sync`。
- 系统依赖需通过 `apt` 安装：`libmagic-dev`、`poppler-utils`、`libreoffice`、`pandoc`、`graphicsmagick` 等，以支持 Office 转 PDF、文档解析及图片处理。
- 首次运行需下载 MinerU 模型：  
  ```bash
  wget https://gcore.jsdelivr.net/gh/opendatalab/MinerU@master/scripts/download_models_hf.py -O download_models_hf.py
  uv run python download_models_hf.py
  ```
- 启动方式：  
  ```bash
  MINERU_MODEL_SOURCE=modelscope uvicorn src.main:app --host 0.0.0.0 --port 7770
  ```  
  也可按 README 中示例在多 GPU 上启动多个实例，或使用 `pm2 start ecosystem.config.json` 等文件管理进程。
- 附属服务容器：  
  - Kroki（图表渲染）：`docker run -d -p 7999:8000 --restart unless-stopped yuzutech/kroki`  
  - Quickchart：`docker run -d -p 7998:3400 --restart unless-stopped ianw/quickchart`  
  - MinIO：参考 README 使用 `quay.io/minio/minio` 镜像。  
  - MinerU vLLM Server：`MINERU_MODEL_SOURCE=modelscope CUDA_VISIBLE_DEVICES=0 mineru-vllm-server --port 30000`

## 开发与质量保障：
- 每次修改代码后，确保运行以下代码格式与质量检查的命令，确保程序质量：
  ```bash
  uv run --group dev black .
  uv run --group dev ruff check src
  uv run --group dev pytest
  ```
- 新增的 `tests/` Pytest 测试工程覆盖配置环境变量覆盖逻辑、Markdown/文件转换工具、MinIO 封装、Pydantic 模型以及 `/health`、`/gpu/status` 等轻量路由；`tests/conftest.py` 会注入轻量替身（GPU 调度器、MinIO/pypdfium2 stub），无需真实外部依赖即可运行。
- 代码中针对 Ruff 规则（F401/BLE001/E722 等）已统一清理未使用依赖，并将异常捕获限定在预期类型；后续新增 try/except 块时请保持同等粒度。
- 图像增强流程的 `_log_vision_prompt` 使用 `logger.debug` 输出前后文，默认不会污染 info 级日志，如需调试可上调日志级别。
- 建议通过 `/health` 做存活探测，`/gpu/status` 监控排队，MinIO/Weaviate 接口应配合真实服务验证。
- 解析路径经常涉及临时文件，注意及时释放；`gpu_scheduler` 已在 finally 中做清理，但新增逻辑时需保持一致。
- VS Code 调试配置（`.vscode/launch.json` 中的 `UnstructureServe`）已关闭 `.venv/**`、`input/**`、`output/**`、`pdfs/**` 等大目录的 reload 监听，以加快首启扫描。

## 常见运维提示
- 若端口被占用，可参考 README 中的 `lsof` + `kill` 脚本快速清理 7770/8770-8772。
- 解析失败常见原因：  
  - Pandoc 未安装或 PATH 配置错误。  
  - MinIO / Weaviate 连接参数缺失或证书配置不当。  
  - GPU 资源不足导致 MinerU 调度超时。
- Office → PDF 转换：每次调用都会为 LibreOffice 创建独立 profile 目录，避免 `.config/libreoffice` 上的锁文件互相影响；若转换超过超时时间会强制中止并清理遗留 `soffice` 进程。
- 从 `/weaviate/` 下的脚本可了解向量库 schema 管理方式，遇到 schema 变更需同步更新 `create_collection_if_not_exists` 默认字段。

## 协作约定
- **重要：以后每次修改，都要同步修改 `AGENTS.md`，确保本文档与代码状态一致。**
- 引入新依赖、环境变量、路由或调整解析流程时，请在此文档补充背景、关键入口与测试方式，方便后续代理与开发者快速接手。
