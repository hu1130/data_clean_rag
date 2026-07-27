export type StatusMode = "success" | "warning" | "danger" | "info";

export interface HealthResponse {
  status: string;
  pipeline_ready: boolean;
}

export interface DiagnosticsResponse {
  diagnostics: Record<string, any>;
}

export interface FileRecord {
  file_key: string;
  filename: string;
  file_type?: string;
  size_bytes?: number;
  document_count?: number;
  chunk_count?: number;
  chunk_ids?: string[];
  status?: string;
  processed_at?: number;
  stats?: Record<string, any>;
  [key: string]: any;
}

export interface FileListResponse {
  backend: string;
  path: string;
  total: number;
  files: FileRecord[];
}

export interface TaskRecord {
  task_id: string;
  action: string;
  status: string;
  created_at: number;
  updated_at: number;
  stats?: Record<string, any> | null;
  error?: string | null;
  progress?: Record<string, any>;
  message?: string;
  attempts?: number;
  max_attempts?: number;
}

export interface DbInfoResponse {
  db_type: string;
  collection_name: string;
  document_count: number;
  metadata?: Record<string, any>;
}

export interface MetadataStatusResponse {
  enabled: boolean;
  type: string;
  store: Record<string, any>;
}

export interface MetadataRun {
  run_id: string;
  status: string;
  input_count?: number;
  stored_count?: number;
  finished_at?: number;
  processing_report?: Record<string, any>;
}

export interface MetadataRunsResponse {
  enabled: boolean;
  runs: MetadataRun[];
}

export interface PreviewResponse {
  stats: Record<string, any>;
  chunks: Array<{ text: string; metadata: Record<string, any> }>;
  total_chunks: number;
  quality_reports: Array<Record<string, any>>;
}

export interface SearchResult {
  id: string;
  text: string;
  score: number;
  metadata: Record<string, any>;
  child_text?: string;
  parent_context?: string;
  context_text?: string;
  parent_id?: string;
  child_id?: string;
  parent_heading_path?: string;
  parent_section_title?: string;
  vector_score?: number;
  rerank_score?: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  total: number;
}

export interface RagAskResponse {
  question: string;
  answer: string;
  provider: string;
  model: string;
  prompt: string;
  sources: SearchResult[];
  total_sources: number;
  usage: Record<string, any>;
  latency_ms: number;
}

export interface ProcessResponse {
  success: boolean;
  stats: Record<string, any>;
  message: string;
  task_id: string;
  status: string;
}

export interface ConfigResponse {
  config: Record<string, any>;
}
