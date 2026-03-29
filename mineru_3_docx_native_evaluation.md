# MinerU 3.x 原生 DOCX 拆解评估

## 背景

当前服务中的 Office 路径默认仍是：

1. API 层先把 `DOCX` / `PPTX` / `XLSX` 等 Office 文件转成 PDF。
2. 再走现有 MinerU `vlm-http-client` 解析链路。
3. 下游继续复用当前的 `chunk_type`、`page_number`、`return_txt`、MinIO 资产落盘、`/mineru_with_images`、`/two_stage/task` 等逻辑。

本次评估的目标不是比较“哪条链路文本更准”这么单一，而是回答下面两个问题：

- MinerU 3.x 新增的原生 `DOCX` 拆解，是否可以直接替换当前 `DOCX -> PDF -> vllm` 默认链路？
- 原生 `DOCX` 是否能覆盖当前服务依赖的开关语义，尤其是 `chunk_type`、`page_number`、`return_txt`、MinIO 相关行为？

结论先行：

- **原生 DOCX 在正文提取精度和速度上有明显优势。**
- **但它不能等价覆盖当前服务默认链路依赖的接口语义。**
- **当前结论是不实施默认切换。**

## 当前服务行为

当前同步接口的 Office 处理入口在 `src/routers/mineru_router.py`，对于 Office 文件会先执行 `maybe_convert_to_pdf()`，然后再交给 GPU 调度器解析。

这意味着当前服务的很多能力，其实是建立在“最终输入一定是 PDF”这个前提上的：

- `page_number` 源自 PDF 解析结果中的 `page_idx`
- `chunk_type` 中的 `title` / `header` / `footer` / `image` 由调度层重新映射
- `save_to_minio` 会写入 `source.pdf` 和逐页 JPEG
- `/mineru_with_images` 与 `/two_stage/task` 的视觉增强逻辑默认认为存在真实页面和页码

## 评估方法

### 样本 1：真实业务文件

使用仓库根目录下的 `公众号.docx` 做 A/B。

对比两条路径：

- **现有路径**
  - `DOCX -> LibreOffice 转 PDF -> vlm-http-client`
- **候选路径**
  - `MinerU 3.0.1 原生 DOCX office 路线`

比较维度：

- 文本保真度
- 图片块数量
- 标题/列表/页眉页脚/页码等结构信息
- 是否能覆盖现有 API 开关语义

### 样本 2：合成兼容性样本

额外临时生成了几个 synthetic DOCX，用来专门验证：

- `Heading 1/2` 是否会输出为 `title` / `text_level`
- `Header/Footer` 是否会单独输出
- Word 显式 `page break` 是否会被拆成多个 `page_idx`
- Word 页码域 `PAGE` 是否会输出为 `page_number`
- Word 列表样式是否会输出为 `list`

## 样本 1：`公众号.docx` 结果

### 文档本体

- 非空正文段落：`28`
- 内嵌图片：`6`

### 现有路径：`DOCX -> PDF -> vllm`

- 总耗时：`4.67s`
- 原始 `content_list.json`：`93` 个块
- 类型分布：`text=73`、`image=10`、`list=10`
- API 语义下可消费文本块：`83`

主要特点：

- 会额外抽到渲染后页面上的视觉文字和视觉块，不只是 DOCX 本体里的段落
- 在这份样本里比原生 DOCX 多识别出一些页面视觉元素
- 但会出现 PDF 渲染 + VLM 路径常见的文本形变

典型问题：

- `20k+` 被写成 `$20\\mathrm{k}+$`
- `100+` 被写成 `$100+$`
- `contact@tiangong.earth` 被写成 `contact@tiangong-earth`

### 原生 DOCX：MinerU 3.0.1 office 路线

- 总耗时：`0.21s`
- 原始 `content_list.json`：`34` 个块
- 类型分布：`text=28`、`image=6`
- API 语义下可消费文本块：`28`

主要特点：

- 正文段落数量与源 DOCX 一致
- 内嵌图片数量与源 DOCX 一致
- 文本保真度明显更好
- 结构更接近“逻辑文档流”，而不是“渲染后的页面视觉理解”

### 段落覆盖结论

以源 DOCX 的 `28` 段正文为基准，按当前 API 实际可消费文本做匹配：

- 现有路径：`25 / 28`
- 原生 DOCX：`28 / 28`

换句话说：

- 如果目标是“尽可能忠实提取 DOCX 里的正文和嵌入图片对象”，原生 DOCX 更好
- 如果目标是“保住当前 PDF 语义、页码和页面视觉块”，现有路径更稳

## 原生 DOCX 实际输出形态

### `content_list.json`

在 `公众号.docx` 这个真实样本上，原生 DOCX 的 `content_list.json` 实际只有：

- `type`
- `text`
- `img_path`
- `image_caption`
- `page_idx`

这一层非常扁平，且全部 `page_idx = 0`。

### `content_list_v2.json`

原生 DOCX 的 richer 结构主要体现在 `content_list_v2.json`：

- 顶层按“页”分组
- 元素使用统一的 `type + content` 结构
- 段内可保留 `bold` / `hyperlink` 等样式信息

但有两个现实问题：

1. 官方文档已经明确说明 `content_list_v2.json` **仍在开发中，格式可能调整**
2. 在 `公众号.docx` 这个样本里，`content_list_v2.json` 只有 `paragraph` 和 `image`，没有页级辅助块，也没有真实分页

因此，`v2` 适合做增强信息的参考来源，不适合直接当作稳定契约替换当前 API 语义。

## 开关兼容性评估

### 1. `chunk_type`

#### `title`

**不能稳定等价覆盖。**

当前服务的 `title` 依赖 `text_level`，并在 `return_txt` 中把标题做双换行。

原生 DOCX 的标题识别取决于 Word 样式是否规范：

- 如果源 DOCX 使用了真实 `Heading 1/2/...` 样式，则原生 office 可以输出 `text_level`
- 如果只是“加粗一行文本”，则不一定会被提升为 `title`

`公众号.docx` 就是典型例子：

- 其中很多看起来像小标题的内容，本质上只是加粗段落
- 原生 DOCX 保留了 `**bold**` 风格，但没有把它们都识别为 `title`

因此：

- 对“规范 Word 文档”来说，`title` 可部分覆盖
- 对“视觉上像标题但其实只是加粗段落”的文档，不可稳定覆盖

#### `header` / `footer`

**可部分覆盖，但不能等价覆盖。**

合成样本表明：

- 真实 Word header/footer 会被原生 office 输出成 `header` / `footer`

但问题在于：

- 这些块仍然挂在单个逻辑页下
- 无法像当前 PDF 路径那样和真实分页一一对应

因此：

- “是否能看到 header/footer 文本”可以
- “是否能维持当前按真实页码分布的 header/footer 语义”不行

#### `image`

**可部分覆盖，但语义不同。**

原生 DOCX 能输出嵌入图片对象，对 `公众号.docx` 来说刚好是 `6` 张。

但当前 `DOCX -> PDF -> vllm` 路径面对类似 PPT 风格的页面时，会把页面渲染后的视觉区域重新理解成更多图像块。`公众号.docx` 在现有路径下就得到了 `10` 个 image-like block。

所以两条链路的 `image` 含义不同：

- 原生 DOCX：更接近“文档里嵌入了哪些图片对象”
- 现有 PDF 路径：更接近“渲染页面后 MinerU/VLM 认为哪些区域是图像块”

#### `list`

**不能稳定覆盖。**

合成样本里专门插入了 Word `List Bullet` 和 `List Number`，结果原生 office 最终都被打平成普通 `paragraph/text`，没有稳定输出为 `list` 块。

也就是说：

- office 路线的 schema 确实支持 `list`
- 但普通 Word 列表样式不代表最终一定能拿到 `list`

这对当前服务是一个兼容性缺口。

### 2. `page_number`

**不能覆盖。**

这是当前不建议切默认链路的核心原因。

真实样本 `公众号.docx`：

- DOCX XML 中存在 `4` 个 `lastRenderedPageBreak`
- 但原生 office 实际只输出 `1` 个逻辑页
- 所有块的 `page_idx` 都是 `0`

合成样本也验证了同样问题：

- 插入显式 `page break`
- 结果仍然只得到 `1` 个逻辑页

进一步补测了 footer 里的 Word 页码域 `PAGE`：

- 原生 office 只保留了 footer 文本
- 没有生成单独的 `page_number` 块

而当前服务里 API 的 `page_number` 是这样来的：

- 解析结果里的 `page_idx`
- 再由服务统一做 `+1`

所以如果直接改走原生 DOCX：

- 几乎所有 chunk 都会落在第 `1` 页
- 当前所有依赖页码的下游逻辑都会出现语义退化

### 3. `return_txt`

**文本内容本身可以，但格式语义不能完全等价覆盖。**

原因：

- 当前 `return_txt` 的标题双换行依赖 `type="title"`
- 原生 DOCX 里很多“视觉标题”未必能变成 `title`
- 原生 DOCX 还可能保留 Markdown 风格的 `**bold**` 或链接渲染结果

因此：

- 纯文本正文往往会更准
- 但标题层级与当前 API 约定的格式感不一定一致

### 4. `save_to_minio`

**不能等价覆盖。**

当前 MinIO 资产上传是以 PDF 为中心的：

- `source.pdf`
- `parsed.json`
- 每页 JPEG

如果走原生 DOCX：

- 没有天然的 `source.pdf`
- 没有天然的逐页 JPEG
- 即使上传嵌入图片，也不是现在的资产语义

也就是说，除非同时继续保留一份 sidecar PDF 专门用于资产落盘，否则当前 MinIO 合同无法保持不变。

### 5. `/mineru_with_images`

**不能等价覆盖。**

原因有两层：

- 页码全部退化成 `1`
- 图片集合本身也和当前 PDF 路径不同

现有路径更像“针对渲染页面上的图像块做视觉增强”；
原生 DOCX 更像“只针对嵌入图片对象做增强”。

这两者不是同一件事。

### 6. `/two_stage/task`

**同样不能等价覆盖。**

因为两段式流程最终也依赖：

- `page_idx -> page_number`
- `image` 块集合
- `chunk_type`

所以原生 DOCX 会继承和同步接口同样的兼容性问题。

### 7. `bbox`

**不能稳定覆盖。**

官方输出文件说明里把 `bbox` 作为通用字段来介绍，但在本次原生 DOCX 实测里：

- `公众号.docx` 没有 bbox
- synthetic DOCX 也没有 bbox

如果后续有脚本依赖 bbox，原生 DOCX 当前不可靠。

## 合成样本结论

### 样本 A：标题、页眉页脚、列表、显式分页

构造内容：

- `Heading 1`
- `Heading 2`
- Header
- Footer
- Bullet list
- Numbered list
- 显式 page break

实测结果：

- `Heading 1/2` 可以输出为 `text_level`
- Header / Footer 可以输出
- 列表被打平成普通文本
- 显式 page break 没有形成多个逻辑页
- 全部仍然是 `page_idx = 0`

### 样本 B：Footer 页码域 `PAGE`

构造内容：

- Header
- Footer 中包含 `PAGE` 域
- 文档中间插入 page break

实测结果：

- 仍然只有 `1` 个逻辑页
- 只保留了 footer 文本 `Page `
- 没有单独 `page_number` 块

## 为什么当前不实施

因为它不只是“文本更不更准”的问题，而是会直接改变现有接口契约。

如果直接把当前默认 Office 路径改成原生 DOCX，会出现：

- `page_number` 基本失真
- `chunk_type.title` 不稳定
- `list` 语义退化
- `save_to_minio` 无法维持当前 PDF 资产合同
- `/mineru_with_images`、`/two_stage/task` 的图像集合和页码语义都会变化

这会导致：

- 外部 API 表面不变
- 但返回值语义已经变了

对接方最难排查的就是这种“字段还在，但含义变了”的升级。

## 当前建议

### 不建议

- 不建议把原生 DOCX 直接替换为默认 Office 解析路径
- 不建议在保持当前 API 契约不变的前提下偷偷切换到底层实现

### 如果未来要引入

更合理的定位是：

- 新增一个可选模式，例如 `docx_native=true`
- 明确标注为“正文优先模式”
- 仅用于对页码不敏感的文本抽取场景

建议前提：

- `save_to_minio=false`
- 不承诺真实页码
- 不承诺和当前 `chunk_type` 完全一致
- 不承诺与当前 `/mineru_with_images` 的视觉块集合一致

## 最终结论

对于 `公众号.docx` 这类以正文内容为主、图片为嵌入对象的文档：

- **原生 DOCX 更准、更快**

但对于当前服务的默认接口能力来说：

- **原生 DOCX 不能完整覆盖现有开关和返回语义**

因此当前决定是：

- **保留现有 `DOCX -> PDF -> vllm` 默认路径**
- **暂不实施原生 DOCX 默认切换**
- **后续如需引入，只考虑作为受限的可选模式**
