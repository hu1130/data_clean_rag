const state = {
  apiBase: localStorage.getItem("dataCleanApiBase") || (
    window.location.protocol.startsWith("http") ? window.location.origin : "http://127.0.0.1:8131"
  ),
  apiKey: localStorage.getItem("dataCleanApiKey") || "",
  activeView: "upload",
  taskTimer: null,
  lastReport: null,
  files: [],
  metadataRuns: [],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function headers(extra = {}) {
  const base = { ...extra };
  if (state.apiKey) base["X-API-Key"] = state.apiKey;
  return base;
}

async function request(path, options = {}) {
  const response = await fetch(`${state.apiBase}${path}`, {
    ...options,
    headers: headers(options.headers || {}),
  });
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const detail = typeof body === "string" ? body : body.detail || response.statusText;
    throw new Error(detail);
  }
  return body;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function asText(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function metric(label, value) {
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(asText(value))}</strong></div>`;
}

function badge(label, value) {
  if (value === null || value === undefined || value === "") return "";
  return `<span class="meta-badge"><strong>${escapeHtml(label)}</strong>${escapeHtml(asText(value))}</span>`;
}

function formatUnixTime(value) {
  const timestamp = Number(value);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return "-";
  return new Date(timestamp * 1000).toLocaleString();
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function explainError(message) {
  const text = String(message || "");
  if (text.includes("Failed to fetch")) return "API 无法访问。确认后端服务已启动，并检查左侧 API 地址。";
  if (text.includes("10061") || text.toLowerCase().includes("connection refused")) return "目标服务拒绝连接。常见原因是 MySQL 或后端服务未启动。";
  if (text.includes("metadata_db")) return "metadata_db 当前未启用。需要查看持久化 chunk 审计时，请使用 MySQL 或 SQLite metadata 配置启动后端。";
  if (text.toLowerCase().includes("ocr") || text.toLowerCase().includes("tesseract")) return "OCR 依赖未就绪。检查 Tesseract 和 Poppler 是否安装并加入 PATH。";
  if (text.includes("401")) return "API Key 不正确或缺失。请在左侧填写后保存。";
  return "查看后端日志或诊断页，确认依赖和配置是否可用。";
}

function renderError(message) {
  return `
    <div class="empty-state error-state">
      <strong>${escapeHtml(message)}</strong>
      <p>${escapeHtml(explainError(message))}</p>
    </div>
  `;
}

function setStatus(label, mode = "neutral") {
  const el = $("#healthStatus");
  el.className = `status-pill ${mode}`;
  el.textContent = label;
}

function addLog(title, message, mode = "info") {
  const list = $("#activityLog");
  const template = $("#logTemplate").content.cloneNode(true);
  const marker = template.querySelector(".log-state");
  if (mode === "error") marker.classList.add("err");
  if (mode === "ok") marker.classList.add("ok");
  template.querySelector("strong").textContent = title;
  template.querySelector("p").textContent = message;
  template.querySelector("time").textContent = new Date().toLocaleTimeString();
  list.prepend(template);
}

function compactMetadata(metadata = {}) {
  const keys = [
    "filename", "file_key", "file_type", "document_part", "heading_path", "parent_heading_path",
    "page_number", "sheet_name", "row_number", "parent_id", "child_id", "chunk_id",
  ];
  const picked = {};
  keys.forEach((key) => {
    if (metadata[key] !== undefined && metadata[key] !== "") picked[key] = metadata[key];
  });
  return picked;
}

function renderReasonBars(reasonCounts = {}) {
  const entries = Object.entries(reasonCounts || {}).sort((a, b) => Number(b[1]) - Number(a[1]));
  if (!entries.length) return `<div class="empty-state compact-empty">没有过滤原因</div>`;
  const max = Math.max(...entries.map(([, count]) => Number(count) || 0), 1);
  return `
    <div class="reason-bars">
      ${entries.map(([reason, count]) => `
        <div class="reason-row">
          <span>${escapeHtml(reason)}</span>
          <div class="reason-track"><i style="width:${Math.max(4, (Number(count) || 0) / max * 100)}%"></i></div>
          <strong>${escapeHtml(count)}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function renderQualityPanel(stats = {}) {
  const quality = stats.quality_summary || {};
  return `
    <div class="quality-grid">
      ${metric("评分数", quality.scored_count)}
      ${metric("拒绝数", quality.rejected_count)}
      ${metric("平均分", quality.average_score)}
      ${metric("保留数", stats.filtered_count)}
    </div>
    ${renderReasonBars(quality.reason_counts || {})}
  `;
}

function renderProcessingReport(report) {
  if (!report) return `<div class="empty-state">暂无报告。上传、预览或打开任务详情后会显示。</div>`;
  const summary = report.summary || {};
  const quality = report.quality_summary || {};
  const parentChild = report.parent_child || {};
  const files = report.files || [];
  const rejected = report.rejected_samples || [];
  const incremental = report.incremental || {};
  const metadataStore = report.metadata_store || {};

  return `
    <div class="report-stack">
      <section class="report-block">
        <h4>总体统计</h4>
        <div class="metric-grid compact">
          ${metric("输入", summary.input_count)}
          ${metric("清洗后", summary.cleaned_count)}
          ${metric("过滤后", summary.filtered_count)}
          ${metric("去重后", summary.deduped_count)}
          ${metric("chunks", summary.chunked_count)}
          ${metric("入库", summary.stored_count)}
        </div>
      </section>
      <section class="report-block">
        <h4>父子 chunk</h4>
        <div class="metric-grid compact">
          ${metric("启用", parentChild.enabled)}
          ${metric("父 chunk", parentChild.parent_count)}
          ${metric("子 chunk", parentChild.child_count)}
          ${metric("父上下文字符", parentChild.parent_context_chars)}
        </div>
      </section>
      <section class="report-block">
        <h4>质量过滤</h4>
        <div class="metric-grid compact">
          ${metric("评分数", quality.scored_count)}
          ${metric("拒绝数", quality.rejected_count)}
          ${metric("平均分", quality.average_score)}
        </div>
        ${renderReasonBars(quality.reason_counts || {})}
      </section>
      <section class="report-block">
        <h4>Route A metadata</h4>
        <div class="metric-grid compact">
          ${metric("启用", metadataStore.enabled)}
          ${metric("类型", metadataStore.type)}
          ${metric("状态", metadataStore.status)}
          ${metric("run_id", metadataStore.run_id)}
        </div>
      </section>
      <section class="report-block">
        <h4>增量处理</h4>
        <div class="metric-grid compact">
          ${metric("处理文件", (incremental.processed || []).length)}
          ${metric("跳过文件", (incremental.skipped || []).length)}
          ${metric("删除旧向量", incremental.deleted_vector_count)}
        </div>
      </section>
      <section class="report-block">
        <h4>文件统计</h4>
        <div class="report-list">
          ${files.map((file) => `
            <article class="report-row">
              <strong>${escapeHtml(file.filename || file.file || "-")}</strong>
              <div class="badge-row">
                ${badge("类型", file.file_type)}
                ${badge("输入", file.input_documents)}
                ${badge("chunks", file.chunks)}
                ${badge("拒绝", file.rejected_documents)}
              </div>
              <code>${escapeHtml(JSON.stringify(file.document_part_counts || {}))}</code>
            </article>
          `).join("") || `<div class="empty-state">暂无文件记录</div>`}
        </div>
      </section>
      <section class="report-block">
        <h4>拒绝样例</h4>
        <div class="report-list">
          ${rejected.map((item) => `
            <article class="report-row">
              <strong>score=${escapeHtml(item.score)}</strong>
              <p>${escapeHtml(item.text_preview || "")}</p>
              <code>${escapeHtml(JSON.stringify(item.reasons || []))}</code>
            </article>
          `).join("") || `<div class="empty-state">没有拒绝样例</div>`}
        </div>
      </section>
    </div>
  `;
}

function renderReport() {
  const output = $("#reportOutput");
  if (output) output.innerHTML = renderProcessingReport(state.lastReport);
}

function setView(viewId) {
  state.activeView = viewId;
  $$(".view").forEach((view) => view.classList.toggle("active-view", view.id === viewId));
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === viewId));
  const titles = {
    upload: "文件入库",
    files: "文件历史",
    tasks: "任务队列",
    preview: "清洗预览",
    search: "检索测试",
    reports: "处理报告",
    system: "系统状态",
    config: "配置管理",
  };
  $("#viewTitle").textContent = titles[viewId] || "工作台";
  if (viewId === "files") refreshFiles();
  if (viewId === "tasks") refreshTasks();
  if (viewId === "reports") renderReport();
  if (viewId === "system") refreshSystem();
  if (viewId === "config") refreshConfig();
}

async function refreshHealth() {
  try {
    const health = await request("/health");
    setStatus(health.pipeline_ready ? "API 就绪" : "Pipeline 未就绪", health.pipeline_ready ? "good" : "warn");
  } catch (error) {
    setStatus("连接失败", "bad");
  }
}

async function refreshSystem() {
  await Promise.allSettled([refreshDiagnostics(), refreshDb(), refreshMetadataRuns()]);
}

async function refreshDiagnostics() {
  const box = $("#diagnosticsOutput");
  box.innerHTML = `<div class="empty-state">加载中</div>`;
  try {
    const data = await request("/api/diagnostics");
    const diagnostics = data.diagnostics || {};
    const ocr = diagnostics.ocr || {};
    const pipeline = diagnostics.pipeline || {};
    const metadataDb = pipeline.metadata_db || {};
    const metadataStore = metadataDb.store || {};
    box.innerHTML = [
      metric("Pipeline", pipeline.ready ? "ready" : "not ready"),
      metric("向量库", pipeline.vector_db),
      metric("Metadata DB", metadataDb.type || "disabled"),
      metric("Metadata 状态", metadataStore.status || "unknown"),
      metric("Embedding", pipeline.embedding?.provider),
      metric("OCR", ocr.ready ? "ready" : "not ready"),
      metric("Tesseract", ocr.tesseract?.available),
      metric("Poppler", ocr.poppler?.available),
      metric("增量", pipeline.ingestion?.manifest_backend || pipeline.ingestion?.manifest_path),
      metric("任务库", pipeline.tasks?.store_path),
    ].join("");
  } catch (error) {
    box.innerHTML = renderError(error.message);
  }
}

async function refreshDb() {
  const box = $("#dbOutput");
  box.innerHTML = `<div class="empty-state">加载中</div>`;
  try {
    const info = await request("/api/db/info");
    box.innerHTML = [
      metric("类型", info.db_type),
      metric("集合", info.collection_name),
      metric("维度", info.dimension),
      metric("数量", info.count),
      metric("状态", info.status),
    ].join("");
  } catch (error) {
    box.innerHTML = renderError(error.message);
  }
}

async function refreshFiles() {
  const rows = $("#fileRows");
  const summary = $("#fileSummaryCards");
  rows.innerHTML = `<tr><td colspan="6">加载中</td></tr>`;
  summary.innerHTML = "";
  try {
    const data = await request("/api/files");
    state.files = data.files || [];
    const totalChunks = state.files.reduce((sum, file) => sum + Number(file.chunk_count || 0), 0);
    const totalSize = state.files.reduce((sum, file) => sum + Number(file.size_bytes || 0), 0);
    summary.innerHTML = [
      metric("文件数", data.total || 0),
      metric("chunk", totalChunks),
      metric("总大小", formatBytes(totalSize)),
      metric("manifest", data.backend || "-"),
    ].join("");
    rows.innerHTML = state.files.length
      ? state.files.map((file) => `
          <tr>
            <td><strong>${escapeHtml(file.filename || file.file_key)}</strong><small>${escapeHtml(file.file_key)}</small></td>
            <td>${escapeHtml(file.file_type || "-")}</td>
            <td>${escapeHtml(file.document_count || 0)}</td>
            <td>${escapeHtml(file.chunk_count || 0)}</td>
            <td>${escapeHtml(formatUnixTime(file.processed_at))}</td>
            <td><button class="text-btn file-detail-btn" data-file-key="${escapeHtml(file.file_key)}" type="button">详情</button></td>
          </tr>
        `).join("")
      : `<tr><td colspan="6">暂无文件记录</td></tr>`;
  } catch (error) {
    rows.innerHTML = `<tr><td colspan="6">${escapeHtml(error.message)}</td></tr>`;
    summary.innerHTML = renderError(error.message);
  }
}

async function showFileDetail(fileKey) {
  const box = $("#fileDetailOutput");
  box.innerHTML = `<div class="empty-state">加载中</div>`;
  try {
    const file = await request(`/api/files/${encodeURIComponent(fileKey)}`);
    box.innerHTML = `
      <div class="detail-stack">
        <div class="metric-grid">
          ${metric("文件", file.filename)}
          ${metric("类型", file.file_type)}
          ${metric("大小", formatBytes(file.size_bytes))}
          ${metric("chunk", file.chunk_count)}
          ${metric("状态", file.status)}
          ${metric("处理时间", formatUnixTime(file.processed_at))}
        </div>
        <h4>chunk ids</h4>
        <code>${escapeHtml(JSON.stringify(file.chunk_ids || [], null, 2))}</code>
        <h4>质量统计</h4>
        <code>${escapeHtml(JSON.stringify(file.stats || {}, null, 2))}</code>
      </div>
    `;
  } catch (error) {
    box.innerHTML = renderError(error.message);
  }
}

async function uploadFiles(event) {
  event.preventDefault();
  const files = $("#fileInput").files;
  if (!files.length) {
    addLog("未选择文件", "请选择至少一个文件。", "error");
    return;
  }

  const form = new FormData();
  const endpoint = files.length === 1 ? "/api/process/file" : "/api/process/files";
  if (files.length === 1) {
    form.append("file", files[0]);
  } else {
    Array.from(files).forEach((file) => form.append("files", file));
  }

  form.append("background", $("#backgroundUpload").checked ? "true" : "false");
  form.append("ocr_enabled", $("#ocrEnabled").checked ? "true" : "false");
  form.append("ocr_language", $("#ocrLanguage").value.trim() || "eng");
  form.append("force_reprocess", $("#forceReprocess").checked ? "true" : "false");
  form.append("incremental", "true");
  form.append("max_file_size_mb", $("#maxFileSize").value || "100");
  if ($("#textFields").value.trim()) form.append("text_fields", $("#textFields").value.trim());
  if ($("#maxRecords").value.trim()) form.append("max_records", $("#maxRecords").value.trim());

  try {
    const result = await request(endpoint, { method: "POST", body: form });
    const status = result.status || "completed";
    const count = result.stats?.stored_count ?? result.stats?.chunked_count ?? 0;
    if (result.stats?.processing_report) {
      state.lastReport = result.stats.processing_report;
      renderReport();
    }
    addLog("入库已提交", `status=${status}, task=${result.task_id}, count=${count}`, "ok");
    if (status === "pending") {
      setView("tasks");
      startTaskPolling();
    } else if (state.lastReport) {
      setView("reports");
    }
  } catch (error) {
    addLog("入库失败", `${error.message}。${explainError(error.message)}`, "error");
  }
}

async function refreshTasks() {
  const body = $("#taskRows");
  body.innerHTML = `<tr><td colspan="7">加载中</td></tr>`;
  try {
    const tasks = await request("/api/tasks");
    if (!tasks.length) {
      body.innerHTML = `<tr><td colspan="7">暂无任务</td></tr>`;
      return;
    }
    body.innerHTML = tasks.map((task) => {
      const progress = task.progress || {};
      const percent = Number(progress.percent || 0);
      return `
        <tr>
          <td><code>${escapeHtml(task.task_id.slice(0, 8))}</code></td>
          <td>${escapeHtml(task.action)}</td>
          <td>${escapeHtml(task.status)}</td>
          <td>
            <div class="progress">
              <div class="bar"><span style="width:${Math.max(0, Math.min(100, percent))}%"></span></div>
              <small>${escapeHtml(progress.stage || "-")} · ${percent}%</small>
            </div>
          </td>
          <td>${task.attempts || 0}/${task.max_attempts || 1}</td>
          <td>${formatUnixTime(task.updated_at || task.created_at)}</td>
          <td><button class="text-btn task-report-btn" data-task-id="${escapeHtml(task.task_id)}" type="button">详情</button></td>
        </tr>
      `;
    }).join("");
  } catch (error) {
    body.innerHTML = `<tr><td colspan="7">${escapeHtml(error.message)}</td></tr>`;
  }
}

async function showTaskReport(taskId) {
  try {
    const task = await request(`/api/tasks/${encodeURIComponent(taskId)}`);
    const report = task.stats?.processing_report || task.stats || null;
    if (!report) {
      addLog("任务暂无报告", taskId, "error");
      return;
    }
    state.lastReport = report;
    renderReport();
    setView("reports");
  } catch (error) {
    addLog("任务详情失败", error.message, "error");
  }
}

function startTaskPolling() {
  if (state.taskTimer) clearInterval(state.taskTimer);
  state.taskTimer = setInterval(() => {
    if (state.activeView === "tasks") refreshTasks();
  }, 2500);
}

async function previewText(event) {
  event.preventDefault();
  const text = $("#previewText").value.trim();
  if (!text) return;
  $("#previewOutput").innerHTML = `<div class="empty-state">加载中</div>`;
  $("#previewQuality").innerHTML = "";
  try {
    const data = await request("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texts: [text], max_chunks: 20, max_chars: 600 }),
    });
    if (data.stats?.processing_report) {
      state.lastReport = data.stats.processing_report;
      renderReport();
    }
    $("#previewQuality").innerHTML = renderQualityPanel(data.stats || {});
    $("#previewCount").textContent = `${data.total_chunks} chunks`;
    $("#previewOutput").innerHTML = data.chunks.map((chunk, index) => `
      <article class="result-item">
        <strong>Chunk ${index + 1}</strong>
        <div class="badge-row">
          ${badge("父", chunk.metadata?.parent_type)}
          ${badge("章节", chunk.metadata?.parent_heading_path || chunk.metadata?.heading_path)}
          ${badge("位置", `${chunk.metadata?.child_index ?? chunk.metadata?.chunk_index ?? 0}/${chunk.metadata?.child_count ?? chunk.metadata?.total_chunks ?? 1}`)}
        </div>
        <p>${escapeHtml(chunk.text)}</p>
        <code>${escapeHtml(JSON.stringify(compactMetadata(chunk.metadata || {}), null, 2))}</code>
      </article>
    `).join("") || `<div class="empty-state">没有可显示的 chunk</div>`;
  } catch (error) {
    $("#previewOutput").innerHTML = renderError(error.message);
  }
}

function renderSearchResult(item, index) {
  const metadata = item.metadata || {};
  const childText = item.child_text || item.text || "";
  const parentContext = item.parent_context || metadata.parent_context || "";
  return `
    <article class="result-item search-result">
      <div class="result-title">
        <strong>${index + 1}. score=${Number(item.score).toFixed(4)}</strong>
        <span>${escapeHtml(item.parent_heading_path || metadata.heading_path || metadata.filename || "")}</span>
      </div>
      <div class="badge-row">
        ${badge("文件", metadata.filename || metadata.file_key)}
        ${badge("父类型", item.parent_type || metadata.parent_type)}
        ${badge("子位置", `${metadata.child_index ?? metadata.chunk_index ?? 0}/${metadata.child_count ?? metadata.total_chunks ?? 1}`)}
        ${badge("页码", metadata.page_number)}
        ${badge("Sheet", metadata.sheet_name)}
        ${badge("行", metadata.row_number)}
      </div>
      <div class="hit-block">
        <span>命中子 chunk</span>
        <p>${escapeHtml(childText)}</p>
      </div>
      ${parentContext ? `
        <details class="parent-context" open>
          <summary>父级上下文</summary>
          <p>${escapeHtml(parentContext)}</p>
        </details>
      ` : ""}
      <code>${escapeHtml(JSON.stringify(compactMetadata(metadata), null, 2))}</code>
    </article>
  `;
}

async function search(event) {
  event.preventDefault();
  const query = $("#searchQuery").value.trim();
  if (!query) return;

  let filters = null;
  const filterText = $("#searchFilter").value.trim();
  if (filterText) {
    try {
      filters = JSON.parse(filterText);
    } catch (error) {
      $("#searchOutput").innerHTML = renderError("filters 不是合法 JSON");
      return;
    }
  }

  $("#searchOutput").innerHTML = `<div class="empty-state">检索中</div>`;
  try {
    const data = await request("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        top_k: Number($("#topK").value || 5),
        filters,
      }),
    });
    $("#searchOutput").innerHTML = data.results.map(renderSearchResult).join("") || `<div class="empty-state">没有结果</div>`;
  } catch (error) {
    $("#searchOutput").innerHTML = renderError(error.message);
  }
}

function renderMetadataRun(run) {
  const report = run.processing_report || {};
  const parentChild = report.parent_child || {};
  return `
    <article class="result-item metadata-run">
      <div class="result-title">
        <strong>${escapeHtml(run.run_id || "-")}</strong>
        <span>${escapeHtml(formatUnixTime(run.finished_at))}</span>
      </div>
      <div class="badge-row">
        ${badge("状态", run.status)}
        ${badge("输入", run.input_count)}
        ${badge("入库", run.stored_count)}
        ${badge("父", parentChild.parent_count)}
        ${badge("子", parentChild.child_count)}
      </div>
      <button class="text-btn metadata-detail-btn" data-run-id="${escapeHtml(run.run_id)}" type="button">查看 chunk 审计</button>
    </article>
  `;
}

async function refreshMetadataRuns() {
  const box = $("#metadataRunsOutput");
  if (!box) return;
  box.innerHTML = `<div class="empty-state">加载中</div>`;
  try {
    const data = await request("/api/metadata/runs?limit=8");
    if (!data.enabled) {
      box.innerHTML = `<div class="empty-state">metadata_db 未启用。启用后可查看持久化批次和 chunk 审计。</div>`;
      return;
    }

    state.metadataRuns = data.runs || [];
    box.innerHTML = state.metadataRuns.length
      ? state.metadataRuns.map(renderMetadataRun).join("")
      : `<div class="empty-state">暂无处理批次</div>`;
  } catch (error) {
    box.innerHTML = renderError(error.message);
  }
}

async function showMetadataRunDetail(runId) {
  const box = $("#metadataRunDetailOutput");
  box.innerHTML = `<div class="empty-state">加载中</div>`;
  try {
    const run = await request(`/api/metadata/runs/${encodeURIComponent(runId)}`);
    const chunks = run.chunks || [];
    box.innerHTML = `
      <div class="detail-stack">
        <div class="metric-grid compact">
          ${metric("run_id", run.run_id)}
          ${metric("状态", run.status)}
          ${metric("入库", run.stored_count)}
          ${metric("chunk 审计", chunks.length)}
        </div>
        <div class="result-list">
          ${chunks.slice(0, 20).map((chunk, index) => `
            <article class="result-item">
              <strong>${index + 1}. ${escapeHtml(chunk.chunk_id)}</strong>
              <div class="badge-row">
                ${badge("文件", chunk.filename || chunk.file_key)}
                ${badge("父", chunk.parent_id)}
                ${badge("位置", `${chunk.child_index}/${chunk.child_count}`)}
              </div>
              <p>${escapeHtml(chunk.text_preview || "")}</p>
              <code>${escapeHtml(JSON.stringify(compactMetadata(chunk.metadata || {}), null, 2))}</code>
            </article>
          `).join("") || `<div class="empty-state">没有 chunk 审计记录</div>`}
        </div>
      </div>
    `;
  } catch (error) {
    box.innerHTML = renderError(error.message);
  }
}

async function refreshConfig() {
  const output = $("#configOutput");
  const summary = $("#configSummary");
  output.value = "加载中";
  summary.innerHTML = "";
  try {
    const data = await request("/api/config");
    const config = data.config || {};
    summary.innerHTML = [
      metric("向量库", config.vector_db?.type),
      metric("Embedding", config.embedding?.provider),
      metric("Metadata DB", config.metadata_db?.type),
      metric("Metadata 启用", config.metadata_db?.enabled),
      metric("chunk size", config.chunking?.chunk_size),
      metric("质量阈值", config.data_cleaning?.quality_filter?.min_score),
    ].join("");
    output.value = JSON.stringify(config, null, 2);
  } catch (error) {
    output.value = error.message;
    summary.innerHTML = renderError(error.message);
  }
}

async function applyConfigPatch(event) {
  event.preventDefault();
  const text = $("#configPatch").value.trim();
  if (!text) return;
  let patch = null;
  try {
    patch = JSON.parse(text);
  } catch (error) {
    addLog("配置格式错误", "配置片段必须是合法 JSON。", "error");
    return;
  }

  try {
    await request("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    addLog("配置已应用", "后端已重新初始化 pipeline。", "ok");
    $("#configPatch").value = "";
    await Promise.allSettled([refreshConfig(), refreshHealth()]);
  } catch (error) {
    addLog("配置应用失败", `${error.message}。${explainError(error.message)}`, "error");
  }
}

function bindEvents() {
  $("#apiBase").value = state.apiBase;
  $("#apiKey").value = state.apiKey;

  $$(".nav-item").forEach((item) => item.addEventListener("click", () => setView(item.dataset.view)));
  $("#saveConnection").addEventListener("click", () => {
    state.apiBase = $("#apiBase").value.replace(/\/$/, "");
    state.apiKey = $("#apiKey").value.trim();
    localStorage.setItem("dataCleanApiBase", state.apiBase);
    localStorage.setItem("dataCleanApiKey", state.apiKey);
    refreshHealth();
    addLog("连接已保存", state.apiBase, "ok");
  });

  $("#refreshAll").addEventListener("click", () => {
    refreshHealth();
    if (state.activeView === "files") refreshFiles();
    if (state.activeView === "tasks") refreshTasks();
    if (state.activeView === "system") refreshSystem();
    if (state.activeView === "config") refreshConfig();
  });

  $("#fileInput").addEventListener("change", () => {
    const files = $("#fileInput").files;
    $("#fileSummary").textContent = files.length
      ? `${files.length} 个文件 · ${Array.from(files).map((file) => file.name).join(", ")}`
      : "未选择文件";
  });

  $("#uploadForm").addEventListener("submit", uploadFiles);
  $("#clearLog").addEventListener("click", () => { $("#activityLog").innerHTML = ""; });
  $("#refreshFiles").addEventListener("click", refreshFiles);
  $("#fileRows").addEventListener("click", (event) => {
    const button = event.target.closest(".file-detail-btn");
    if (button?.dataset.fileKey) showFileDetail(button.dataset.fileKey);
  });
  $("#refreshTasks").addEventListener("click", refreshTasks);
  $("#taskRows").addEventListener("click", (event) => {
    const button = event.target.closest(".task-report-btn");
    if (button?.dataset.taskId) showTaskReport(button.dataset.taskId);
  });
  $("#previewForm").addEventListener("submit", previewText);
  $("#searchForm").addEventListener("submit", search);
  $("#refreshDiagnostics").addEventListener("click", refreshDiagnostics);
  $("#refreshDb").addEventListener("click", refreshDb);
  $("#refreshMetadataRuns").addEventListener("click", refreshMetadataRuns);
  $("#metadataRunsOutput").addEventListener("click", (event) => {
    const button = event.target.closest(".metadata-detail-btn");
    if (button?.dataset.runId) showMetadataRunDetail(button.dataset.runId);
  });
  $("#refreshConfig").addEventListener("click", refreshConfig);
  $("#configForm").addEventListener("submit", applyConfigPatch);
}

bindEvents();
refreshHealth();
startTaskPolling();
