# 多卡 MinerU / vLLM 高性能高兼容改造 Todo

## 背景与结论

当前项目已经把 MinerU 3.x 封装到 FastAPI 服务中，并在服务侧补了 MinIO、视觉增强、Celery 两段式队列、Office 转 PDF 等能力。对“很多张卡”的生产场景，推荐优先采用下面这条主线：

- 默认解析链路保持 `vlm-http-client`
- 每张 GPU 单独启动一个 OpenAI-compatible MinerU / vLLM 服务实例
- 主服务只做上传、Office 预处理、MinIO、任务编排、结果回填与统一入口
- 图像增强继续走独立队列，与解析阶段拆分
- `vlm-vllm-async-engine` 仅作为后续可选“快车道”，不作为默认后端

这样做的目标是同时兼顾：

- 多卡扩展性
- 故障隔离
- 兼容性
- 维护复杂度
- 回滚成本

## 非目标

- 当前阶段不把整个项目重写成异步 FastAPI 架构
- 当前阶段不把默认后端切到 `vlm-vllm-async-engine`
- 当前阶段不推翻现有 `/mineru`、`/mineru_with_images`、`/two_stage/*` 接口合同

## 总体实施阶段

### Phase 0: 现状基线

- [ ] 梳理当前生产/测试环境的 GPU 数量、型号、显存、驱动、CUDA 版本
- [ ] 梳理当前部署形态：
  - 主服务实例数
  - `mineru-vllm-server` 实例数
  - Celery worker 数
  - Redis / MinIO 部署位置
- [ ] 记录当前关键瓶颈：
  - GPU 利用率
  - 平均单文档耗时
  - P95 / P99 延迟
  - 失败率
  - 最常见报错类型
- [ ] 记录当前大文件、长文档、Office 文档、图片密集文档的表现差异
- [ ] 明确当前流量模型：
  - 同步接口占比
  - 异步任务占比
  - `/mineru_with_images` 占比
  - `/two_stage/task` 占比

### Phase 1: 部署拓扑收敛

- [ ] 约定“每张 GPU 一个 OpenAI-compatible server”的统一部署规范
- [ ] 为每张卡分配固定端口，例如 `30000` 到 `3000N`
- [ ] 为每个推理实例分配固定设备绑定：
  - `CUDA_VISIBLE_DEVICES=<gpu_id>`
  - 单卡单进程
- [ ] 统一主服务的 `MINERU_VLLM_SERVER_URLS` 配置格式
- [ ] 明确主服务只通过 URL 池访问推理层，不再假设本地单卡默认 `30000`
- [ ] 补一份标准化部署矩阵：
  - 单机 4 卡
  - 单机 8 卡
  - 多机多卡
- [ ] 明确故障隔离策略：
  - 单个端点失败时自动轮转其他端点
  - 单卡重启不影响主服务存活

### Phase 2: 主服务代码改造

#### 2.1 调度层从“GPU 槽”改成“远端推理槽”

- [ ] 评估是否保留 `src/services/gpu_scheduler.py` 文件名
- [ ] 若保留文件名，至少在类/注释/变量层明确区分：
  - 本地 GPU worker
  - 远端 endpoint slot
- [ ] 引入“推理槽数量”概念，不再默认用 `GPU_IDS` 代表并发度
- [ ] 增加配置项，例如：
  - `MINERU_REMOTE_PARSE_SLOTS`
  - 或自动取 `MINERU_VLLM_SERVER_URLS` 的 URL 数量
- [ ] 调整 `scheduler.submit()` 的分配逻辑，使其与 endpoint 数量而不是本地 GPU 数绑定
- [ ] 保留现有硬超时机制，避免远端请求卡死拖垮 worker

#### 2.2 端点池与容错

- [ ] 在 `src/services/mineru_service_full.py` 现有 URL 轮转基础上补充更明确的失败处理策略
- [ ] 为端点失败增加分类：
  - 连接失败
  - 读超时
  - 服务端 5xx
  - 明确业务错误
- [ ] 评估是否需要熔断窗口：
  - 短期内多次失败的端点临时降权
  - 一段时间后自动恢复探测
- [ ] 为请求日志增加 endpoint 维度，方便定位坏卡/坏实例
- [ ] 为结果统计增加 endpoint 维度成功率

#### 2.3 配置面整理

- [ ] `.env.example` 增加多端点配置示例
- [ ] README 增加“单机多卡 URL 池”部署示例
- [ ] PM2 / systemd / Docker Compose 模板补多实例写法
- [ ] 为每种部署方式明确：
  - 主服务配置
  - 解析服务配置
  - 视觉服务配置
  - Celery worker 配置

### Phase 3: 视觉与解析彻底拆池

- [ ] 保持两段式方案作为高吞吐主线
- [ ] 解析队列只绑定 MinerU 解析卡池
- [ ] 视觉队列只绑定视觉模型卡池
- [ ] 明确解析卡池与视觉卡池是否允许复用同一组 GPU
- [ ] 如果复用，定义资源抢占优先级
- [ ] 如果拆分，定义最低配置：
  - 解析卡最少数量
  - 视觉卡最少数量
- [ ] 为 `src/services/two_stage_pipeline.py` 补一份建议并发值矩阵：
  - `parse worker concurrency`
  - `vision worker concurrency`
  - `dispatch worker concurrency`
  - `merge worker concurrency`

### Phase 4: `vlm-vllm-async-engine` 快车道（可选）

- [ ] 只在同构、已验证稳定的 NVIDIA 集群上试点
- [ ] 不改变默认后端，新增“快车道”配置开关
- [ ] 将 async backend 的启用范围限制为：
  - 指定环境
  - 指定队列
  - 指定接口
- [ ] 补充 `MINERU_API_MAX_CONCURRENT_REQUESTS` 的调优区间
- [ ] 记录 async 模式的典型异常：
  - connection closed
  - server pressure
  - timeout
  - 结果不稳定
- [ ] 定义自动回退策略：
  - async 失败后是否重试到 `vlm-http-client`
  - 是否仅对幂等异步任务开启重试
- [ ] 明确哪些平台不启用 async：
  - MooreThreads
  - Cambricon
  - 其他官方标注不稳定的平台

### Phase 5: 可观测性

- [ ] 增加以下指标：
  - 每个 endpoint 的请求数
  - 每个 endpoint 的失败率
  - 每个 endpoint 的平均耗时 / P95 / P99
  - 主服务排队深度
  - Celery 队列积压
  - 单文档页数分布
  - Office 转 PDF 成功率
- [ ] 增加日志字段：
  - `backend`
  - `server_url`
  - `gpu_id` 或 `endpoint_id`
  - `task_id`
  - `document_type`
  - `page_count`
- [ ] 增加坏实例定位能力：
  - 连续失败告警
  - GPU 健康检查
  - 端点摘除/恢复记录

### Phase 6: 压测与验收

#### 6.1 压测集准备

- [ ] 建立标准压测数据集：
  - 短 PDF
  - 长 PDF
  - 图片密集 PDF
  - 表格密集 PDF
  - 扫描件
  - DOCX / PPTX / XLSX
- [ ] 每类样本准备至少一批可重复回放的数据
- [ ] 为每类样本记录期望输出与已知问题

#### 6.2 压测维度

- [ ] 对比三种模式：
  - 当前主线
  - 多端点 `vlm-http-client`
  - async 快车道（若启用）
- [ ] 观察指标：
  - 吞吐
  - P95
  - P99
  - GPU 利用率
  - CPU 利用率
  - 失败率
  - 端点负载均衡程度
- [ ] 做单卡、4 卡、8 卡、跨机扩展性测试

#### 6.3 验收标准

- [ ] 单卡故障不导致整体服务不可用
- [ ] 新架构下主服务不需要本地加载 VLM 权重
- [ ] 增加 GPU 数后吞吐近线性提升或至少明显提升
- [ ] Office、Markdown、MinIO、视觉增强合同不回归
- [ ] 同步接口与 Celery 接口返回结构保持兼容

## 具体文件级 Todo

### 代码

- [ ] `src/services/gpu_scheduler.py`
  - 评估重命名或重构为 endpoint-aware scheduler
  - 将并发单位从 GPU 改为 endpoint slot
  - 保留硬超时与 finally 清理
- [ ] `src/services/mineru_service_full.py`
  - 强化多 URL 轮转、失败重试、日志
  - 明确默认 `vlm-http-client` 路径的生产部署建议
- [ ] `src/services/two_stage_pipeline.py`
  - 按解析/视觉/汇总继续保持独立队列
  - 视需要增加更细粒度的 worker 配置
- [ ] `src/services/mineru_task_runner.py`
  - 校验异步任务也遵循新的 endpoint slot 调度策略

### 文档

- [ ] `README.md`
  - 新增多卡部署章节
  - 新增多端点配置示例
  - 新增压测建议
- [ ] `AGENTS.md`
  - 在相关章节记录最终方案和新增环境变量
- [ ] 新增或更新运维文档
  - PM2 示例
  - Docker Compose 示例
  - systemd 示例

### 测试

- [ ] `tests/test_mineru_backend.py`
  - 补 endpoint/slot 相关配置测试
- [ ] `tests/test_two_stage_pipeline_parse.py`
  - 补多端点/失败切换测试
- [ ] 新增 scheduler 专项测试
  - 槽位分配
  - 失败回收
  - 超时清理
- [ ] 新增集成测试
  - 多 URL 轮转
  - 单端点故障回退
  - 两段式队列在高并发下的稳定性

## 推荐最终形态

### 默认生产形态

- [ ] 主服务默认 backend 维持 `vlm-http-client`
- [ ] 所有解析请求打到 `MINERU_VLLM_SERVER_URLS`
- [ ] 每张卡单独运行一个 `mineru-openai-server` 或 `mineru-vllm-server`
- [ ] `/two_stage/task` 作为大吞吐主入口
- [ ] 视觉队列与解析队列分离

### 可选高性能形态

- [ ] 在受控环境中单独提供 async 快车道
- [ ] 与默认生产链路完全解耦
- [ ] 仅在验证通过的平台与 GPU 型号上开启

## 运维上线步骤

- [ ] 先在测试环境起 2 卡版本验证 URL 池
- [ ] 再扩到 4 卡做吞吐验证
- [ ] 再扩到生产卡数
- [ ] 上线初期仅切一部分流量
- [ ] 保留旧部署与旧配置，支持快速回滚
- [ ] 回滚条件提前写清楚：
  - 失败率异常
  - P99 恶化
  - 单卡雪崩
  - 两段式任务长时间堆积

## 待确认问题

- [ ] 当前生产负载是同步接口为主还是异步任务为主
- [ ] 视觉模型是否与 MinerU 共卡部署
- [ ] 是否存在跨机多卡需求
- [ ] 是否允许在主服务侧做 endpoint 熔断与临时摘除
- [ ] 是否需要按租户 / 优先级做不同队列或不同卡池
- [ ] 是否需要把解析结果缓存到对象存储或 Redis 以减轻重试成本

## 建议的落地顺序

1. 先补部署与配置文档，统一“每卡一个 server + 主服务 URL 池”的规范。
2. 再改调度层，把并发单位从本地 GPU 改成远端 endpoint slot。
3. 再做可观测性与压测，验证吞吐、稳定性、故障隔离。
4. 最后再评估是否值得引入 `vlm-vllm-async-engine` 快车道。
