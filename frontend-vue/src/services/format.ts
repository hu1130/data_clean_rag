export function formatUnixTime(value?: number) {
  if (!value) return "-";
  return new Date(value * 1000).toLocaleString();
}

export function formatBytes(value?: number) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function shortId(value?: string, size = 8) {
  if (!value) return "-";
  return value.length <= size * 2 ? value : `${value.slice(0, size)}...${value.slice(-size)}`;
}

export function statusType(status?: string) {
  const normalized = String(status || "").toLowerCase();
  if (["healthy", "ready", "succeeded", "completed", "processed", "success"].includes(normalized)) return "success";
  if (["running", "pending", "retry_scheduled"].includes(normalized)) return "warning";
  if (["failed", "error", "bad", "missing"].includes(normalized)) return "danger";
  return "info";
}

export function asJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}
