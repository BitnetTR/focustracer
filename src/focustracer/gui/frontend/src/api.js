/**
 * FocusTracer API client
 */

const BASE = '/api'

async function apiFetch(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${path} → ${res.status}: ${text}`)
  }
  return res.json()
}

export const api = {
  getSettings: () => apiFetch('/settings'),
  saveSettings: (data) => apiFetch('/settings', { method: 'POST', body: JSON.stringify(data) }),

  agentsStatus: () => apiFetch('/agents/status'),
  systemInfo: () => apiFetch('/system/info'),
  ollamaMetrics: (model) => apiFetch(`/ollama/metrics${model ? `?model=${encodeURIComponent(model)}` : ''}`),
  ollamaModels: () => apiFetch('/ollama/models'),
  pullModel: (data) => apiFetch('/ollama/pull', { method: 'POST', body: JSON.stringify(data) }),

  listFiles: (root) => apiFetch(`/files?root=${encodeURIComponent(root)}`),
  fileContent: (path) => apiFetch(`/file-content?path=${encodeURIComponent(path)}`),
  getInventory: (root, script) =>
    apiFetch(`/inventory?root=${encodeURIComponent(root)}&script=${encodeURIComponent(script)}`),

  listOutputs: (projectRoot) =>
    apiFetch(`/outputs${projectRoot ? `?project_root=${encodeURIComponent(projectRoot)}` : ''}`),
  getOutput: (path) => apiFetch(`/output?path=${encodeURIComponent(path)}`),

  runTrace: (data) => apiFetch('/trace/run', { method: 'POST', body: JSON.stringify(data) }),
  suggestTrace: (data) => apiFetch('/trace/suggest', { method: 'POST', body: JSON.stringify(data) }),
  getJob: (jobId) => apiFetch(`/job/${jobId}`),

  // Trace analysis (parity with CLI: slice / reverse / replay / align / explain)
  sliceTrace: (data) => apiFetch('/trace/slice', { method: 'POST', body: JSON.stringify(data) }),
  reverseTrace: (data) => apiFetch('/trace/reverse', { method: 'POST', body: JSON.stringify(data) }),
  replayTrace: (data) => apiFetch('/trace/replay', { method: 'POST', body: JSON.stringify(data) }),
  // Two paths => side-by-side aligned cursor; three or more => trace-set curation.
  alignTraces: (data) => apiFetch('/trace/align', { method: 'POST', body: JSON.stringify(data) }),
  alignDistance: (data) => apiFetch('/trace/align/distance', { method: 'POST', body: JSON.stringify(data) }),
  explainTrace: (data) => apiFetch('/trace/explain', { method: 'POST', body: JSON.stringify(data) }),
}

/**
 * Subscribe to SSE stream for a job.
 * @param {string} jobId
 * @param {(entry: object) => void} onMessage
 * @param {(status: string, result: any) => void} onDone
 * @returns {() => void} unsubscribe function
 */
export function subscribeJobStream(jobId, onMessage, onDone) {
  const es = new EventSource(`/api/trace/stream/${jobId}`)
  es.onmessage = (e) => {
    const data = JSON.parse(e.data)
    if (data.kind === 'done') {
      onDone(data.status, data.result)
      es.close()
    } else {
      onMessage(data)
    }
  }
  es.onerror = () => {
    onDone('error', null)
    es.close()
  }
  return () => es.close()
}
