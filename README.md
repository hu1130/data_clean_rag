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
| POST | `/api/process` | 处理文本列表 |
| POST | `/api/process/file` | 上传单个文件处理 |
| POST | `/api/process/files` | 批量上传文件处理 |
| POST | `/api/search` | 语义搜索 |
| GET | `/api/search?query=xxx` | GET 方式搜索 |
| GET | `/api/db/info` | 数据库信息 |
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

## 核心功能

### 数据清洗
- **文本清洗**：去除 HTML 标签、URL、邮箱、规范化空白
- **质量过滤**：字数检查、乱码检测、语言过滤
- **去重**：精确去重 / MinHash 近似去重

### 文本分块
- **递归分块**：优先在段落、句子边界处分割
- **固定分块**：按固定大小分割
- **重叠机制**：保持上下文连续性

### 嵌入模型
- **本地模型**：BGE、Sentence-BERT 等（默认 BAAI/bge-large-zh-v1.5）
- **云端模型**：OpenAI Embedding API

### 向量数据库
| 数据库 | 特点 | 适用场景 |
|--------|------|----------|
| ChromaDB | 本地持久化，零配置 | 原型开发、小规模应用 |
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
  deduplication:
    enabled: true
    method: minhash
    threshold: 0.85

chunking:
  enabled: true
  chunk_size: 512
  chunk_overlap: 128

embedding:
  model_name: "BAAI/bge-large-zh-v1.5"

vector_db:
  type: chroma
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
