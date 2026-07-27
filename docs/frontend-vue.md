# Vue 前端说明

新版前端位于 `frontend-vue/`，旧版 `frontend/` 暂时保留用于回退。

## 技术栈

- Vue 3
- Vite
- TypeScript
- Element Plus
- ECharts
- axios

## 页面

- 工作台：状态、最近任务、最近文件、质量概览
- 文件入库：批量上传、OCR、后台处理、强制重建、字段配置
- 文件管理：manifest 文件历史、详情抽屉
- 清洗预览：清洗/质量过滤/chunk 预览，不写入向量库
- Chunk 审计：metadata_db 批次和 chunk metadata 审计
- 检索测试：直接调用 `/api/search`
- RAG 测试台：先接检索链路，生成 prompt 和引用证据
- 任务中心：后台任务队列、进度、报告
- 质量报告：metadata 批次趋势和过滤原因图表
- 系统配置：诊断、配置查看、配置片段更新

## 本地运行

```powershell
cd frontend-vue
npm install
npm run dev
```

默认开发地址：

```text
http://127.0.0.1:5173
```

Vite 会把 `/api` 和 `/health` 代理到：

```text
http://127.0.0.1:8131
```

## 构建

```powershell
cd frontend-vue
npm run build
```

构建产物输出到 `frontend-vue/dist/`。等 Vue 版稳定后，再把 FastAPI 的 `/app` 静态目录切到该构建产物。
