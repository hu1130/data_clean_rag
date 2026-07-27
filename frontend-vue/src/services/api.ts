import axios from "axios";
import type {
  ConfigResponse,
  DbInfoResponse,
  DiagnosticsResponse,
  FileListResponse,
  FileRecord,
  HealthResponse,
  MetadataRunsResponse,
  MetadataStatusResponse,
  PreviewResponse,
  ProcessResponse,
  RagAskResponse,
  SearchResponse,
  TaskRecord
} from "../types/api";

const api = axios.create({
  baseURL: localStorage.getItem("dataCleanApiBase") || "",
  timeout: 30000
});

api.interceptors.request.use((config) => {
  const key = localStorage.getItem("dataCleanApiKey");
  if (key) {
    config.headers["X-API-Key"] = key;
  }
  return config;
});

export function setApiBase(baseUrl: string) {
  const normalized = baseUrl.replace(/\/$/, "");
  localStorage.setItem("dataCleanApiBase", normalized);
  api.defaults.baseURL = normalized;
}

export function setApiKey(key: string) {
  localStorage.setItem("dataCleanApiKey", key.trim());
}

export function getApiBase() {
  return localStorage.getItem("dataCleanApiBase") || "http://127.0.0.1:8131";
}

export function getApiKey() {
  return localStorage.getItem("dataCleanApiKey") || "";
}

export function explainApiError(error: unknown) {
  if (axios.isAxiosError(error)) {
    if (!error.response || error.code === "ERR_NETWORK") {
      return "无法连接后端服务，请确认服务已启动并检查 API 地址";
    }
    if (error.response.status === 401 || error.response.status === 403) {
      return "后端拒绝了当前连接，请检查 API Key";
    }
    const detail = error.response?.data?.detail || error.response?.data || error.message;
    if (typeof detail === "string") {
      if (/^Request failed with status code/i.test(detail)) {
        return `后端请求失败（HTTP ${error.response.status}），请检查服务日志`;
      }
      return detail;
    }
    return JSON.stringify(detail);
  }
  return error instanceof Error ? error.message : String(error);
}

export const backendApi = {
  health: async () => (await api.get<HealthResponse>("/health")).data,
  diagnostics: async () => (await api.get<DiagnosticsResponse>("/api/diagnostics")).data,
  files: async () => (await api.get<FileListResponse>("/api/files")).data,
  fileDetail: async (fileKey: string) => (await api.get<FileRecord>(`/api/files/${encodeURIComponent(fileKey)}`)).data,
  tasks: async () => (await api.get<TaskRecord[]>("/api/tasks")).data,
  taskDetail: async (taskId: string) => (await api.get<TaskRecord>(`/api/tasks/${encodeURIComponent(taskId)}`)).data,
  dbInfo: async () => (await api.get<DbInfoResponse>("/api/db/info")).data,
  metadataStatus: async () => (await api.get<MetadataStatusResponse>("/api/metadata/status")).data,
  metadataRuns: async () => (await api.get<MetadataRunsResponse>("/api/metadata/runs?limit=12")).data,
  metadataRunDetail: async (runId: string) => (await api.get<Record<string, any>>(`/api/metadata/runs/${encodeURIComponent(runId)}`)).data,
  config: async () => (await api.get<ConfigResponse>("/api/config")).data,
  updateConfig: async (patch: Record<string, any>) => (await api.post("/api/config", patch)).data,
  preview: async (payload: Record<string, any>) => (await api.post<PreviewResponse>("/api/preview", payload)).data,
  search: async (payload: Record<string, any>) => (await api.post<SearchResponse>("/api/search", payload)).data,
  ragAsk: async (payload: Record<string, any>) => (
    await api.post<RagAskResponse>("/api/rag/ask", payload, { timeout: 120000 })
  ).data,
  uploadFiles: async (formData: FormData) => (
    await api.post<ProcessResponse>("/api/process/files", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 120000
    })
  ).data
};
