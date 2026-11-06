export function memorySearchPath(filter, offset = 0) {
  const params = new URLSearchParams({ offset: String(offset), limit: "100" });
  if (filter.agent) params.set("agent_id", filter.agent);
  if (filter.namespace) params.set("namespace", filter.namespace);
  if (filter.status) params.set("status", filter.status);
  if (filter.requestId?.trim()) params.set("request_id", filter.requestId.trim());
  if (filter.memoryId) params.set("memory_id", filter.memoryId);
  if (filter.parentId) params.set("parent_id", filter.parentId);
  return `/memories?${params}`;
}
