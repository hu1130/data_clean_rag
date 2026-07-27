# 数据清洗 + 向量数据库项目

一个完整的端到端数据清洗和向量存储解决方案，支持多种向量数据库和嵌入模型。





## 后端 API 服务

基于 **FastAPI** 构建的高性能 RESTful API，为前端提供数据清洗、向量存储和语义搜索能力。

### 技术选型

选择 **FastAPI** 作为 API 框架的原因：
- **性能**: 基于 ASGI + async/await，吞吐量是 Flask 的 3-5 倍 [^14^]
- **类型安全**: Pydantic v2 自动校验请求/响应数据
- **自动文档**: 内置 Swagger UI 和 ReDoc，无需手写 API 文档
- **AI 生态**: 与 LangChain、LlamaIndex 等 AI 工具链深度集成 [^15^]
- **并发处理**: 原生支持高并发 AI 推理请求 [^16^]

### 启动后端服务

```bash
# 安装依赖（包含 FastAPI）
pip install -r requirements.txt

# 启动 API 服务
python -m api.main
# 或
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 访问自动生成的 API 文档
# Swagger UI: http://localhost:8000/docs
# ReDoc:      http://localhost:8000/redoc
```

### API 端点一览

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/` | 服务状态 |
| GET | `/health` | 健康检查 |
| GET | `/api/diagnostics` | 环境诊断：复杂文件依赖、OCR、pipeline 配置 |
| POST | `/api/process` | 处理文本列表 |
| POST | `/api/process/file` | 上传单个文件处理 |
| POST | `/api/process/files` | 批量上传文件处理 |
| POST | `/api/search` | 语义搜索 |
| GET | `/api/search?query=xxx` | GET 方式搜索 |
| GET | `/api/db/info` | 数据库信息 |
| GET | `/api/metadata/status` | Route A 元数据数据库状态 |
| GET | `/api/metadata/runs` | 最近处理批次 |
| GET | `/api/metadata/runs/{run_id}` | 单次处理批次详情 |
| DELETE | `/api/db/clear` | 清空数据库 |
| GET | `/api/config` | 获取配置 |
| POST | `/api/config` | 更新配置 |

### 前端与后端联调

```bash
# 终端 1：启动后端
cd data_cleaning_vector_db
python -m api.main --port 8000

# 终端 2：启动前端（静态文件服务器）
cd data_cleaning_vector_db/frontend
python -m http.server 8080

# 浏览器访问 http://localhost:8080
# 前端会自动连接 http://localhost:8000 的 API
```

### 生产部署

```bash
# 使用 Gunicorn + Uvicorn 工作进程
pip install gunicorn
gunicorn api.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# 或使用 Docker
docker run -p 8000:8000 -v $(pwd)/config.yaml:/app/config.yaml your-image
```


## 项目结构

```
data_cleaning_vector_db/
├── config.yaml              # 主配置文件
├── main.py                  # 主入口
├── example.py               # 使用示例
├── requirements.txt         # 依赖列表
├── README.md                # 项目说明
├── 使用手册.md               # 详细使用手册
├── src/                     # 后端核心代码
│   ├── __init__.py
│   ├── pipeline.py          # 主流水线
│   ├── cleaning/            # 数据清洗模块
│   │   ├── text_cleaner.py  # 文本清洗
│   │   └── deduplicator.py  # 去重
│   ├── chunking/            # 分块模块
│   │   └── chunkers.py      # 分块器
│   ├── embedding/           # 嵌入模型
│   │   └── models.py        # 模型封装
│   └── vector_db/           # 向量数据库
│       └── adapters.py      # 数据库适配器
├── frontend/                # 前端控制台
│   ├── index.html           # 主页面
│   ├── style.css            # 样式表
│   └── app.js               # 交互逻辑
└── data/
    ├── raw/                 # 原始数据
    └── cleaned/             # 清洗后数据
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 准备数据

将原始文本文件放入 `data/raw/` 目录，支持 `.txt`、`.md`、`.json` 格式。

### 3. 运行流水线

```bash
# 使用 ChromaDB（本地，无需额外服务）
python main.py --input data/raw/ --db chroma

# 使用 Qdrant（需要先启动 Qdrant 服务）
python main.py --input data/raw/ --db qdrant

# 执行搜索查询
python main.py --input data/raw/ --db chroma --query "你的搜索问题"
```

### 4. 运行示例

```bash
python example.py
```

## 开发与调试功能

### 本地快速启动

仓库提供 `config.dev.yaml`，使用内存向量库和轻量 Hash 嵌入，适合本地验证 API 和处理流程：

```bash
python -m api.main --host 127.0.0.1 --port 8010 --config config.dev.yaml
```

启动后可以打开前端控制台：

```bash
http://127.0.0.1:8010/app
```

控制台支持文件上传入库、任务队列查看、清洗预览、搜索测试、处理报告、诊断和向量库状态查看。若设置了 `API_KEY`，在左侧连接面板填写同一个 Key。

检查当前机器是否具备复杂文件解析和 OCR 能力：

```bash
python main.py --check-env
curl -H "X-API-Key: your-secret" http://127.0.0.1:8010/api/diagnostics
```

如需保护 API，设置 `API_KEY` 环境变量。设置后，所有 `/api/*` 数据接口都需要携带 `X-API-Key` 或 Bearer Token：

```bash
# PowerShell
$env:API_KEY="your-secret"
python -m api.main --host 127.0.0.1 --port 8010 --config config.dev.yaml

# 请求示例
curl -H "X-API-Key: your-secret" http://127.0.0.1:8010/api/db/info
```

### 后台处理任务

处理大文本或批量文件时，可以在请求里加 `background: true`，接口会立即返回 `task_id`：

```json
{
  "texts": ["long document"],
  "background": true
}
```

查询任务状态：

```bash
GET /api/tasks/{task_id}
GET /api/tasks
```

任务状态响应包含 `progress` 字段，格式为 `stage`、`percent`、`message`，用于观察大文件处理进度。当前阶段包括 `starting`、`cleaning`、`quality_filter`、`deduplication`、`chunking`、`embedding`、`storing`、`completed`、`failed`。

后台任务会写入 SQLite 队列，由 API 内置 worker 领取执行。任务状态、进度、结果和错误会持久化；服务重启后，带 payload 的未完成任务会重新排队，无法恢复 payload 的旧任务会标记为 `interrupted`。配置位于 `config.yaml`：

```yaml
tasks:
  enabled: true
  store_path: "data/tasks.sqlite3"
  max_history: 100
  worker_enabled: true
  max_attempts: 2
  retry_delay_seconds: 5
  lease_timeout_seconds: 3600
  poll_interval_seconds: 1.0
```

### 预览清洗和分块

不生成向量、不写入数据库，只查看清洗、过滤、去重和分块结果：

```bash
python main.py --config config.dev.yaml --input data/raw/ --preview --preview-limit 5
```

API 也支持预览：

```bash
POST /api/preview
```

预览响应会返回 `quality_reports`，用于查看被过滤文本的 `score`、`reasons` 和 `metrics`。这适合在正式入库前调试复杂数据的清洗规则。

前端“报告”页会展示 `stats.processing_report`，包括输入数、清洗数、过滤数、chunk 数、入库数、父子 chunk 统计、文件级统计和拒绝样例。

### 复杂数据输入

文件加载现在支持 `.txt`、`.md`、`.json`、`.jsonl`、`.csv`、`.html`、`.pdf`、`.docx`、`.xlsx`、`.xlsm`、`.png`、`.jpg`、`.jpeg`、`.tif`、`.tiff`、`.bmp`。

JSON/JSONL/CSV 会优先读取 `text`、`content`、`body`、`page_content` 等常见字段，也支持 `data.body` 这种嵌套字段，并保留文件名、页码、行号、表格行号、sheet 名等元数据。

复杂 Office/PDF 文件会尽量保留结构信息：

- PDF：按页输出文档，metadata 包含 `page_number`、`total_pages`，并尝试从页面首行推断 `section_title`
- 扫描版 PDF：默认会返回明确错误并提示需要 OCR；启用 `ocr_enabled` 后会对空文本页执行 OCR
- 图片文件：需要启用 OCR，metadata 会标记 `ocr_applied`、`ocr_backend`、`ocr_language`
- DOCX：默认按标题层级拆分，metadata 包含 `section_title`、`heading_path`、`heading_level`、`table_count`
- Excel：默认按数据行拆分，自动识别表头，支持多级表头和合并单元格填充，metadata 包含 `sheet_name`、`row_number`、`headers`、`merged_ranges`

处理复杂文档需要安装可选依赖：

```bash
pip install pypdf python-docx openpyxl beautifulsoup4

# OCR 可选依赖；还需要系统安装 Poppler 和 Tesseract
pip install pdf2image pillow pytesseract
```

CLI 可以指定字段、大小限制和记录数限制：

```bash
python main.py --config config.dev.yaml --input data/raw/ --preview \
  --text-field data.body \
  --max-file-size-mb 200 \
  --max-records 10000 \
  --ocr \
  --ocr-language chi_sim+eng \
  --ocr-max-pages 20
```

正式入库时默认启用增量处理：系统会用文件 hash 判断文件是否变化，未变化的文件会跳过，变化的文件会删除旧 chunk 向量后重新入库。manifest 默认使用 SQLite，适合长期运行和多请求写入；仍可切回 JSON。可用参数：

```bash
python main.py --config config.dev.yaml --input data/raw/ --db memory
python main.py --config config.dev.yaml --input data/raw/ --no-incremental
python main.py --config config.dev.yaml --input data/raw/ --force-reprocess
python main.py --config config.dev.yaml --input data/raw/ --manifest-backend sqlite --manifest-path data/manifest.sqlite3
python main.py --config config.dev.yaml --input data/raw/ --manifest-backend json --manifest-path data/manifest.json
```

仓库还提供 `test_files/complex_samples/` 作为复杂样例集，覆盖 Markdown 合同、CSV 客服记录、JSONL 嵌套字段、OCR 噪声文本和 HTML 网页导出。

### 一键验收测试

本地验收使用开发配置，不依赖外部模型或外部向量库：

```bash
python scripts/acceptance_check.py
```

脚本会自动执行：

- `python -m unittest discover -s tests`
- `node --check frontend/app.js`
- 加载 `test_files/complex_samples/` 和测试 DOCX
- 跑清洗、质量过滤、父子 chunk、入库和搜索
- 生成 JSON 和 Markdown 验收结果

输出目录：

```text
reports/acceptance/
```

人工验收模板位于：

```text
docs/验收报告模板.md
```

说明：默认配置不会切换到 SQLite；`config.dev.yaml` 仍使用 `memory` 向量库，便于快速测试。MySQL/生产数据库采用路线 A：MySQL 保存业务 metadata、处理批次、文件报告和 chunk 审计记录，向量库仍独立负责向量检索。

### Route A：MySQL + 向量库

生产建议采用“两库分工”：

- MySQL：保存文件元数据、处理批次、清洗统计、质量过滤报告、父子 chunk 审计记录。
- 向量库：保存 embedding 向量并执行相似度检索，例如 Chroma/Qdrant/Milvus。
- API：`/api/metadata/status` 查看元数据存储状态，`/api/metadata/runs` 查看最近处理批次，`/api/metadata/runs/{run_id}` 查看单次处理详情。

开启 MySQL metadata 存储：

```yaml
metadata_db:
  enabled: true
  type: "mysql"
  fail_on_error: true
  mysql:
    host: "127.0.0.1"
    port: 3306
    database: "data_clean_rag"
    user: "data_clean_rag"
    password_env: "MYSQL_PASSWORD"
    charset: "utf8mb4"
```

PowerShell 示例：

```powershell
$env:MYSQL_PASSWORD="your-password"
python -m api.main --host 127.0.0.1 --port 8010 --config config.yaml
```

启用后服务启动时会自动创建 `metadata_processing_runs`、`metadata_files`、`metadata_chunks` 三张表。开发测试仍建议保持 `metadata_db.enabled: false`，或临时改成 `type: sqlite` 验证写入链路。

MySQL 建库脚本位于：

```text
deploy/mysql/metadata_schema.sql
```

DBA 可先执行：

```bash
mysql -u root -p < deploy/mysql/metadata_schema.sql
```

本机真实 MySQL 路线 A 验证配置位于：

```text
config.mysql.example.yaml
```

连接并写入一条探针记录：

```powershell
$env:MYSQL_PASSWORD="your-password"
python scripts/mysql_metadata_check.py --config config.mysql.example.yaml
```

只验证连接和建表，不写探针记录：

```powershell
$env:MYSQL_PASSWORD="your-password"
python scripts/mysql_metadata_check.py --config config.mysql.example.yaml --schema-only
```

验证通过后，用真实 MySQL metadata 启动 API：

```powershell
$env:MYSQL_PASSWORD="your-password"
python -m api.main --host 127.0.0.1 --port 8132 --config config.mysql.example.yaml
```

上传文件接口也支持表单参数：

| 参数 | 说明 |
|------|------|
| `text_fields` | 逗号分隔的字段名，如 `text,content,data.body` |
| `max_file_size_mb` | 单文件最大大小，默认 100 |
| `max_records` | JSONL/CSV/Excel 每个文件最多读取记录数 |
| `excel_header_row` | Excel 表头起始行；不传则使用第一个非空行 |
| `excel_header_rows` | Excel 表头占用行数，默认 1；适合多级表头 |
| `excel_row_documents` | 是否按 Excel 数据行拆分文档，默认 true |
| `docx_split_by_heading` | 是否按 DOCX 标题层级拆分，默认 true |
| `pdf_infer_sections` | 是否从 PDF 页面文本推断章节标题，默认 true |
| `ocr_enabled` | 是否启用扫描 PDF / 图片 OCR，默认 false |
| `ocr_backend` | OCR 后端，当前支持 `tesseract` |
| `ocr_language` | OCR 语言，如 `eng`、`chi_sim+eng` |
| `ocr_dpi` | PDF OCR 渲染 DPI，默认 200 |
| `ocr_max_pages` | 最多 OCR 的 PDF 空文本页数 |
| `incremental` | 是否启用文件 hash 增量跳过，默认 true |
| `force_reprocess` | 即使 hash 未变化也强制重新处理，默认 false |

增量配置位于 `config.yaml` 的 `ingestion`：

```yaml
ingestion:
  incremental: true
  manifest_backend: "sqlite"
  manifest_path: "data/manifest.sqlite3"
```

### 元数据过滤搜索

`POST /api/search` 支持 `filters`，可以按入库时的元数据过滤：

```json
{
  "query": "semantic search",
  "top_k": 5,
  "filters": {
    "filename": "alpha.md"
  }
}
```

## 核心功能

### 数据清洗
- **文本清洗**：去除 HTML 标签、URL、邮箱、规范化空白
- **质量过滤**：字数检查、乱码检测、语言过滤
- **去重**：精确去重 / MinHash 近似去重

### 文本分块
- **递归分块**：优先在段落、句子边界处分割
- **固定分块**：按固定大小分割
- **重叠机制**：保持上下文连续性
- **父子 chunk**：默认把原始章节/页面/行作为父 chunk，把向量检索单元作为子 chunk；子 chunk metadata 包含 `parent_id`、`child_id`、`parent_type`、`parent_context`、`parent_heading_path`

### 嵌入模型
- **本地模型**：BGE、Sentence-BERT 等（默认 BAAI/bge-large-zh-v1.5）
- **云端模型**：OpenAI Embedding API
- **开发模式**：`provider: hash` 可在无模型下载时验证完整链路
- **重排序**：可选 `cross_encoder` reranker；本地测试可使用 `keyword` reranker
- **处理报告**：`stats.processing_report` 返回文件级输入、chunk、过滤原因、embedding 和 reranker 配置摘要

### 向量数据库
| 数据库 | 特点 | 适用场景 |
|--------|------|----------|
| ChromaDB | 本地持久化，零配置 | 原型开发、小规模应用 |
| SQLite | 单文件持久化，无外部服务 | 本地长期测试、小规模数据 |
| Qdrant | 高性能，REST API | 生产环境、大规模数据 |
| Milvus | 分布式，云原生 | 企业级应用 |
| Weaviate | GraphQL 接口 | 复杂查询场景 |

## 配置说明

编辑 `config.yaml` 自定义处理流程：

```yaml
data_cleaning:
  text_cleaning:
    remove_html: true
    min_length: 10
    max_length: 5000
  quality_filter:
    enabled: true
    min_word_count: 2
    max_word_count: 1000
    min_score: 60
    max_symbol_ratio: 0.35
    max_digit_ratio: 0.80
    max_repeated_char_ratio: 0.30
    max_repeated_line_ratio: 0.50
    max_mojibake_ratio: 0.02
    max_ocr_noise_ratio: 0.45
  deduplication:
    enabled: true
    method: minhash
    threshold: 0.85

chunking:
  enabled: true
  chunk_size: 512
  chunk_overlap: 128
  parent_child:
    enabled: true
    parent_context_chars: 1200

embedding:
  provider: sentence_transformers   # hash / sentence_transformers / openai
  model_name: "BAAI/bge-large-zh-v1.5"
  batch_size: 32

reranker:
  enabled: false
  type: cross_encoder               # cross_encoder / keyword
  model_name: "BAAI/bge-reranker-base"
  candidate_top_k: 20

vector_db:
  type: chroma
  sqlite:
    path: "data/vectors.sqlite3"
    collection_name: "documents"
```

## 代码中使用

```python
from src.pipeline import DataPipeline

# 初始化
pipeline = DataPipeline("config.yaml")
pipeline.init_vector_db("chroma")

# 处理数据
texts = ["文本1", "文本2", "文本3"]
stats = pipeline.process_texts(texts)

# 搜索
results = pipeline.search("查询内容", top_k=5)
for r in results:
    print(r['text'])

# 关闭
pipeline.close()
```

## 处理流程

```
原始数据 → 文本清洗 → 质量过滤 → 去重 → 分块 → 嵌入 → 向量数据库
```

## 性能优化建议

1. **批处理**：使用 `batch_size` 参数调整嵌入批大小
2. **GPU 加速**：设置 `device: cuda` 使用 GPU
3. **增量更新**：只处理新增数据，避免全量重建
4. **索引优化**：生产环境使用 HNSW 索引加速搜索
