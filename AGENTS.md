# TianGong AI Unstructure Serve 代理说明

## 项目概览
- 这是一个基于 FastAPI 的非结构化文档解析服务，负责统一封装 MinerU 文档解析、Markdown 转档、MinIO 对象存储以及视觉问答能力。
- 主入口在 `src/main.py`，通过依赖注入决定是否开启 Bearer Token 鉴权，并集中挂载各类路由（健康检查、GPU 调度、MinerU 解析、Markdown 转 DOCX、MinIO 上传下载等）。
- GPU 解析任务由自研调度器 `src/services/gpu_scheduler.py` 进行统一排队、超时控制和多进程执行，保障 MinerU 解析稳定性。
- 视觉模型封装在 `src/services/vision_service.py`，按环境变量动态选择 OpenAI、Gemini 或 vLLM 服务，并对模型列表、默认模型及凭证做运行时校验；OpenAI 与 vLLM 通过 `src/services/vision_service_openai_compatible.py` 复用同一套 OpenAI-compatible 客户端池，提示词生成集中在 `src/services/vision_prompts.py`。
- `src/main.py` 初始化根日志记录器为 INFO，并将 `httpx`/`httpcore` 日志级别降至 WARNING，避免打印请求详情。

## 目录速览
- `src/routers/`：各业务路由。`mineru_router.py`/`mineru_sci_router.py`/`mineru_with_images_router.py` 针对不同解析流程，`mineru_task_router.py`/`mineru_with_images_task_router.py` 分别提供 MinerU 普通版与图像版的 Celery 入队与状态查询，`markdown_router.py` 负责 Markdown→DOCX，`minio_router.py` 负责对象存储操作，`gpu_router.py` 暴露调度状态，`health_router.py` 提供健康检查；`mineru_minio_utils.py` 复用 MinerU 解析的 MinIO 前后处理逻辑。
- `src/services/`：服务层实现。包含 MinerU 解析全流程（含图片/科研版）、Markdown 生成、MinIO 封装、视觉模型调用及 GPU 调度；`celery_app.py` 提供 Celery 单例配置，`tasks/mineru_tasks.py`/`mineru_task_runner.py` 负责 MinerU 异步任务执行。
- `src/utils/`：工具函数，例如统一 JSON 响应包装、Markdown 预处理、Office→PDF 转换、MinerU 支持文件扩展名查询、纯文本导出等。
- `src/models/`：Pydantic 数据模型，描述 API 的入参与返回结构（如 `ResponseWithPageNum`（含可选 `txt`/`minio_assets` 字段）等）。
- 根目录还包含 `README.md`（环境配置与运维命令）、多个 `ecosystem*.json`（pm2 启动模板）以及 `pyproject.toml`/`uv.lock`（依赖声明）。

## 核心功能
- **MinerU 文档解析**（`src/routers/mineru_router.py` 等）  
  - 支持 PDF、Office、Markdown 等格式，利用 `maybe_convert_to_pdf` 先行格式统一，再调用 GPU 调度器执行 MinerU 管线。  
  - 可选通过 `return_txt` 返回纯文本串（标题段落追加 `\n\n`、普通段落 `\n`）及内容类型标签，结果统一映射到 `TextElementWithPageNum` 模型。
  - MinerU 后端由环境变量 `MINERU_DEFAULT_BACKEND` 控制；允许值：`pipeline`/`vlm-transformers`/`vlm-vllm-engine`/`vlm-lmdeploy-engine`/`vlm-http-client`/`vlm-mlx-engine`，接受 `hybrid-auto-engine`/`hybrid-http-client`（当前 MinerU 2.7.0 wheel 未包含 hybrid 实现，内部回退至 `vlm-vllm-engine`/`vlm-http-client`）。API 不再接受表单参数覆盖后端。校验与规范化逻辑见 `src/utils/mineru_backend.py`。  
  - 当调用端传入 `chunk_type=true` 时，解析结果除了保留标题（`type="title"`）外，还会额外返回页眉与页脚片段（`type="header"`/`"footer"`），并将页眉放在结果列表顶部；`page_number` 类型仍被忽略，且 `return_txt=true` 时的纯文本输出会按同样顺序拼接。
  - `/mineru` 与 `/mineru_with_images` 均支持 `save_to_minio` 与 `minio_*` 表单字段，成功时会在 `mineru/<文件名>`（可自定义 `minio_prefix`）下写入源 PDF、解析 JSON 与逐页 JPEG，并通过响应体的 `minio_assets` 摘要返回上传结果；当 `chunk_type=true` 时，写入 MinIO 的 `parsed.json` 会保留 `type` 字段（header/footer/title）以便下游消费。两者唯一差异是 `/mineru_with_images` 会额外调用视觉大模型（`pipeline="images"`）为图像生成描述。
  - 额外可选字段 `minio_meta` 会在 `save_to_minio=true` 时把传入字符串写入 `meta.txt`（与 `source.pdf` 同目录），返回的 `minio_assets.meta_object` 会指向该文件，便于下游查阅附加元信息；若 `save_to_minio=false`，后端会安全地忽略该字段，避免调用端因默认值冲突而报错。
  - `mineru_minio_utils.build_minio_prefix()` 支持保留 Unicode/中文字符及常见中文标点，但所有空格（含全角空格）都会被统一替换为 `_`，其余不可打印字符也会折叠为 `_` 并清理多余分隔符。对应校验见 `tests/test_mineru_minio_utils.py`。
- **MinerU 异步队列**（`src/routers/mineru_task_router.py`/`mineru_with_images_task_router.py` + `src/services/tasks/mineru_tasks.py`）  
  - 基于 Celery+Redis 提供 `/mineru/task` 与 `/mineru/task/{task_id}`（纯文本解析）以及 `/mineru_with_images/task` 与 `/mineru_with_images/task/{task_id}`（图像感知版）状态查询，返回 `task_id` 及 Celery `state`（PENDING/STARTED/SUCCESS/FAILURE 等）。  
  - 路由校验与同步接口一致：仅接受 `mineru_supported_extensions`/Office/Markdown，Markdown 不允许 `save_to_minio`。上传文件会落地到 `MINERU_TASK_STORAGE_DIR`（默认系统临时目录的 `tiangong_mineru_tasks` 子目录），Celery 任务结束后自动清理。  
  - `priority` 表单字段控制队列：`urgent` 走 `queue_urgent`，其他值走 `queue_normal`（可通过环境覆盖）。  
  - 任务执行仍复用 `gpu_scheduler` 和 `mineru_task_runner.run_mineru_local_job`：Office 自动转 PDF，解析结果过滤页眉页脚规则与同步接口保持一致，支持 MinIO 上传与 `minio_meta` 写入；图像版 Celery 任务（`mineru.parse_images`）会额外透传 `vision_provider`/`vision_model`/`vision_prompt` 到 `parse_with_images`。
- **MinIO 对象操作**（`src/routers/minio_router.py`）  
  - 封装上传/下载所需的 endpoint 解析、bucket 校验与对象名规范化，所有异常以 HTTP 错误返回。  
  - `/minio/upload` 接收标准的 `UploadFile` 表单字段；`/minio/upload/base64` 提供 Base64 版入口（字段 `file_base64`，可选 `content_type_override`），两者共用内置工具完成对象存储写入并在内容为空时返回 400。  
  - `build_storage_collection_name` 会在 MinIO 操作中对 `collection_name`/`user_id` 做统一合法化，沿用之前 `KB_<USER>_<COLLECTION>` 的存储前缀避免路径混乱。  
  - 通用配置结构 `MinioConfig` 写在 `src/services/minio_storage.py`。
- **Markdown 工具链**（`src/routers/markdown_router.py` & `src/services/markdown_service.py`）  
  - 允许上传 Markdown 文本和可选的 reference DOCX 模板，将内容转换为 DOCX 并按需清理文档样式（依赖 Pandoc 与 python-docx）。
- **GPU 调度与监控**（`src/services/gpu_scheduler.py`）  
  - 按 GPU ID 创建 `ProcessPoolExecutor`，每个任务在独立子进程执行，并设有硬超时以防解析卡死。  
  - `/gpu/status` 路由可以查询每块 GPU 的排队任务数及运行情况。
- **视觉问答/解析**（`src/services/vision_service.py`）  
  - 统一调度 OpenAI、Gemini、vLLM 视觉大模型；OpenAI 与 vLLM 通过 `vision_service_openai_compatible.py` 共用 OpenAI-compatible 客户端池（支持多个 base_url 轮询），OpenAI 需配置 `OPENAI_API_KEY`，vLLM 使用 `VLLM_BASE_URLS`/`VLLM_BASE_URL`（可逗号分隔）或 `VLLM_API_KEY`，兼容 `LLM_BASE_URLS`/`LLM_BASE_URL` 别名。
  - 提示词构建集中在 `vision_prompts.py`，默认文案已明确要求模型直接输出核心洞察，禁止使用“根据您提供的上下文信息”“以下是”等前置客套语。
  - 当 vLLM 仅提供 base_url 而未配置密钥时，会使用占位 key（`not-required`）落到相同的 OpenAI-compatible 请求路径。
  - `/mineru_with_images` 的图像描述按 `VISION_BATCH_SIZE` 分批并发调用视觉服务（默认 3、下限 1），上下文在调用前统一基于文本/列表/表格/图像 caption 计算（受 `VISION_CONTEXT_WINDOW` 控制），不会再把已生成的视觉描述写回上下文；图片无需连续也可并行，识别结果最终按原文顺序回填。
- **两段式 MinerU+视觉并行（新增示例服务）**  
  - 新增 `src/services/two_stage_pipeline.py` 定义独立 Celery 应用与任务：`two_stage.parse`（仅 MinerU 解析，GPU 队列）、`two_stage.vision`（单图视觉请求，视觉队列）、`two_stage.merge`（汇总）、`two_stage.dispatch`（fan-out+合并 orchestrator）。队列名可由 `CELERY_TASK_PARSE_QUEUE`/`CELERY_TASK_VISION_QUEUE`/`CELERY_TASK_DISPATCH_QUEUE`/`CELERY_TASK_MERGE_QUEUE` 控制，默认沿用 `CELERY_TASK_MINERU_QUEUE` / `default` / `queue_vision`。工作空间默认 `MINERU_TASK_STORAGE_DIR`，解析完成后在 merge 清理。  
  - 新增 `src/routers/two_stage_router.py` 暴露 `/two_stage/task` 与 `/two_stage/task/{task_id}`，已在 `src/main.py` 默认挂载；亦保留独立入口 `src/two_stage_app.py`（`uvicorn src.two_stage_app:app --host 0.0.0.0 --port 7780`）按需单独部署。支持 PDF 及 Office（API 侧先用 `maybe_convert_to_pdf` 转 PDF），`chunk_type`/`return_txt`/`provider`/`model`/`prompt` 可选。  
  - Worker 示例（可按需调整并发）：解析队列 `celery -A src.services.two_stage_pipeline worker -Q queue_parse_gpu -P threads -c 1 -l info`；视觉队列 `celery -A src.services.two_stage_pipeline worker -Q queue_vision -P threads -c 32 -l info`；调度队列 `celery -A src.services.two_stage_pipeline worker -Q queue_dispatch -P threads -c 4 -l info`；汇总队列（处理 merge）`celery -A src.services.two_stage_pipeline worker -Q default -P threads -c 4 -l info`。调度与汇总拆分可避免 dispatch 阻塞 merge 导致 chord 一直处于 active 状态。`submit_two_stage_job` 帮助方法可直接在代码中调用。  
  - 该示例用于解耦 MinerU 解析与视觉阶段，避免 GPU 和视觉卡互相空转；已通过 `main.py` 暴露路由，可直接在现有服务中访问 `/two_stage/*`，也可按需用独立入口部署。
  - 两段式解析中如 MinerU 抛异常或未返回内容，`parse_doc` 会直接抛出 `RuntimeError`（包含 “do_parse returned None” 等提示），并将异常继续冒泡，`two_stage.parse` 会捕获并带上源文件路径返回给 Flower，避免再出现 “cannot unpack non-iterable NoneType object” 之类的报错。视觉阶段与 `/mineru_with_images` 对齐：`provider`/`model`/`prompt`（空字符串会清空为 None）会透传给 `vision_completion`，可通过请求参数或 `VISION_PROVIDER`/`VISION_MODEL` 环境变量指定模型；路由层使用 `VisionProvider`/`VisionModel` 进行校验，Swagger 会给出枚举提示。  
  - 视觉合并规则：若原图有 caption/footnote 则合并为 `<原文本>\nImage Description: <视觉输出>`；无原始文本时直接用视觉输出，默认不带 `type`，`chunk_type=true` 仅为标题/页眉/页脚打标。  
- PM2 模板：`ecosystem.two_stage.celery.json`（三类 worker）和 `ecosystem.two_stage.flower.json`（两段式 Flower，默认 5556 端口，继承两段式队列环境）。

## 配置与敏感信息
- 所有默认配置来自 `.secrets/secrets.toml`，通过 `src/config/config.py` 读取；文件顶部会先 `load_dotenv()`，确保 `.env` 环境变量优先级更高（容器/CI 可直接覆盖）。敏感字段包括 FASTAPI Bearer Token、OpenAI/Gemini/VLLM API Key 等。
  - 运行/调试方式：优先在 `.env` 中放敏感值与运行时模型选择；`ecosystem.config.json` 仅用于非敏感覆盖（如超时参数），避免在 PM2 配置中写入密钥或 vLLM base_url。PM2 启动时先加载 `.env`，再应用 `env` 块覆盖同名字段。
- 关键环境变量：  
  - `FASTAPI_AUTH` / `FASTAPI_BEARER_TOKEN` / `FASTAPI_MIDDLEWARE_SECRECT_KEY`：是否开启 Bearer 鉴权及令牌值、中间件密钥。  
  - `MINERU_*`：控制 MinerU 模型源、VLM 服务地址、任务超时时间；新增 `.env` 默认的 MinerU 解析策略：`MINERU_DEFAULT_BACKEND`（默认 `vlm-http-client`，可选 `pipeline`/`vlm-transformers`/`vlm-vllm-engine`/`vlm-lmdeploy-engine`/`vlm-http-client`/`vlm-mlx-engine`，接受 `hybrid-*` 并在当前 wheel 下回退至对应 vlm backend）、`MINERU_DEFAULT_LANG`（默认 `ch`）、`MINERU_DEFAULT_METHOD`（默认 `auto`），通过 `python-dotenv` 在解析进程中自动加载。  
    - `MINERU_HYBRID_BATCH_RATIO`：hybrid-* 小模型 batch 倍率（默认 8，仅 hybrid 模式有效，用于控制显存占用）。  
    - `MINERU_VLLM_API_KEY` / `MINERU_VLLM_AUTH_HEADER`：为 MinerU `vlm-http-client` 注入 HTTP Authorization 头；优先使用完整的 `MINERU_VLLM_AUTH_HEADER`，否则从 `MINERU_VLLM_API_KEY` 生成 `Bearer <key>`。  
    - `MINERU_OFFICE_CONVERT_TIMEOUT_SECONDS`：LibreOffice Office→PDF 转换超时时间（默认 180s），超时会终止转换并返回 500。  
    - `OPENAI_API_KEY` / `GENIMI_API_KEY`：视觉/生成模型凭证，支持以环境变量覆盖默认 secrets。  
    - `VISION_PROVIDER_CHOICES`、`VISION_MODELS_*`：视觉模型白名单。  
  - `VISION_BATCH_SIZE`：`/mineru_with_images` 视觉描述的批处理并发度（默认 3，最小 1），调整以配合模型限流。  
  - `VLLM_BASE_URL` / `VLLM_BASE_URLS` / `VLLM_API_KEY`：指定 vLLM 视觉服务地址/凭证，支持逗号分隔配置多实例，按轮询方式调用（`.secrets/secrets.toml` 支持 `BASE_URL` 与 `BASE_URLS` 两种字段），兼容 `LLM_BASE_URL`/`LLM_BASE_URLS` 环境别名。  
    - `MINIO_*`：MinIO 凭证与目标桶。  
    - `CUDA_VISIBLE_DEVICES`：运行时显卡绑定。  
    - `MINERU_HYBRID_BATCH_RATIO` / `MINERU_HYBRID_FORCE_PIPELINE_ENABLE`：hybrid-* 小模型 batch 倍率（默认 8）与强制文本提取走小模型（默认 false）；仅 hybrid 模式生效。  
  - `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`：Celery broker/结果存储（默认均指向 `redis://localhost:6379/0`）；`CELERY_TASK_DEFAULT_QUEUE`（默认 `default`）、`CELERY_TASK_MINERU_QUEUE`（默认 `queue_normal`）、`CELERY_TASK_URGENT_QUEUE`（默认 `queue_urgent`）控制队列名，`CELERY_RESULT_EXPIRES` 控制结果过期时间（秒）。  
  - `MINERU_TASK_STORAGE_DIR`：MinerU Celery 任务的本地落地目录，默认 `tempfile.gettempdir()/tiangong_mineru_tasks`，需保证 worker 与 API 主进程均可读写。
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
- Celery/Flower：  
  ```bash
  # 启动 worker（监听 urgent + normal + default，确保 src.services.tasks 被发现）
  # 注意：GPU 调度内部再起子进程，Celery worker 需使用非 daemonic 池，推荐 -P solo -c 1
  CELERY_BROKER_URL=redis://localhost:6379/0 uv run celery -A src.services.celery_app worker -l info -Q queue_urgent,queue_normal,default -P solo -c 1
  # 监控
  CELERY_BROKER_URL=redis://localhost:6379/0 uv run celery -A src.services.celery_app flower --address=0.0.0.0 --port=5555
  ```
  - PM2 模板：`ecosystem.celery.json` 以 `.venv/bin/python` 作为 interpreter 执行 `.venv/bin/celery`，避免 PM2 默认用 Node 解释脚本导致 SyntaxError。
  - Flower PM2 模板：`ecosystem.celery.flower.json` 同样用 `.venv/bin/python` 解释 `.venv/bin/celery`，默认 `--address=0.0.0.0 --port=5555`，环境中写死 broker/result backend 为本地 Redis。
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
- 新增的 `tests/` Pytest 测试工程覆盖配置环境变量覆盖逻辑、Markdown/文件转换工具、MinIO 封装、Pydantic 模型以及 `/health`、`/gpu/status` 等轻量路由；`tests/conftest.py` 会注入轻量替身（GPU 调度器、MinIO/pypdfium2 stub），无需真实外部依赖即可运行。两段式相关：`tests/test_two_stage_router.py` 覆盖 `/two_stage/task` 的无扩展名错误与成功入队（通过 monkeypatch stub 掉 Celery 调度），批量送入两段式 Celery 的脚本移到 `src/scripts/two_stage_enqueue.py`（读取 `pdfs` 目录提交 `/two_stage/task`，轮询完成后将响应中的 result 持久化到 `pickle/<stem>.pkl`，默认遇到失败会记录并继续其余文件，支持 `TWO_STAGE_*` 环境覆盖）；`tests/test_two_stage_pipeline_parse.py` 验证 MinerU 返回空/异常时的错误传播，确保任务失败能在 Flower 中看到具体原因。
- 代码中针对 Ruff 规则（F401/BLE001/E722 等）已统一清理未使用依赖，并将异常捕获限定在预期类型；后续新增 try/except 块时请保持同等粒度。
- 图像增强流程的 `_log_vision_prompt` 使用 `logger.debug` 输出前后文，默认不会污染 info 级日志，如需调试可上调日志级别。
- 建议通过 `/health` 做存活探测，`/gpu/status` 监控排队，MinIO 接口应配合真实服务验证。
- 解析路径经常涉及临时文件，注意及时释放；`gpu_scheduler` 已在 finally 中做清理，但新增逻辑时需保持一致。
- VS Code 调试配置（`.vscode/launch.json` 中的 `UnstructureServe`）已关闭 `.venv/**`、`input/**`、`output/**`、`pdfs/**` 等大目录的 reload 监听，以加快首启扫描。

## 常见运维提示
- 若端口被占用，可参考 README 中的 `lsof` + `kill` 脚本快速清理 7770/8770-8772。
- 解析失败常见原因：  
  - Pandoc 未安装或 PATH 配置错误。  
  - MinIO 连接参数缺失或证书配置不当。  
  - GPU 资源不足导致 MinerU 调度超时。
- Office → PDF 转换：每次调用都会为 LibreOffice 创建独立 profile 目录，避免 `.config/libreoffice` 上的锁文件互相影响；若转换超过超时时间会强制中止并清理遗留 `soffice` 进程。

## 协作约定
- **重要：以后每次修改，都要同步修改 `AGENTS.md`，确保本文档与代码状态一致。**
- 引入新依赖、环境变量、路由或调整解析流程时，请在此文档补充背景、关键入口与测试方式，方便后续代理与开发者快速接手。
