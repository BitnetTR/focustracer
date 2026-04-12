import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'
import {
  FolderOpen, Settings, Play, Zap, ChevronRight, ChevronDown,
  FileCode2, X, RefreshCw, CheckCircle2, XCircle, AlertCircle,
  Cpu, Terminal, Download, Eye, Clock, FileText, Loader2,
  Folder, LayoutGrid, Activity, GitBranch, Server, Gauge, Flame
} from 'lucide-react'
import { api, subscribeJobStream } from './api.js'
import './App.css'

// ─── Tag Input ──────────────────────────────────────────────────────────────
function TagInput({ value, onChange, placeholder }) {
  const [input, setInput] = useState('')
  const inputRef = useRef(null)

  const addTag = (v) => {
    const tag = v.trim()
    if (tag && !value.includes(tag)) onChange([...value, tag])
    setInput('')
  }
  const removeTag = (tag) => onChange(value.filter(t => t !== tag))

  const onKeyDown = (e) => {
    if ((e.key === 'Enter' || e.key === ',') && input.trim()) {
      e.preventDefault(); addTag(input)
    }
    if (e.key === 'Backspace' && !input && value.length) removeTag(value[value.length - 1])
  }

  return (
    <div className="tag-input-container" onClick={() => inputRef.current?.focus()}>
      {value.map(tag => (
        <span key={tag} className="tag">
          {tag}
          <span className="tag-remove" onClick={() => removeTag(tag)}>×</span>
        </span>
      ))}
      <input
        ref={inputRef}
        className="tag-input-field"
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => input.trim() && addTag(input)}
        placeholder={value.length === 0 ? placeholder : ''}
      />
    </div>
  )
}

// ─── File Tree ───────────────────────────────────────────────────────────────
function TreeNode({ node, depth, onSelect, selectedPath }) {
  const [open, setOpen] = useState(depth < 1)
  const isDir = node.type === 'dir'
  const isActive = !isDir && node.path === selectedPath

  return (
    <div>
      <div
        className={`tree-item ${isDir ? 'dir' : ''} ${isActive ? 'active' : ''}`}
        style={{ paddingLeft: `${14 + depth * 14}px` }}
        onClick={() => isDir ? setOpen(o => !o) : onSelect(node)}
      >
        {isDir
          ? (open ? <ChevronDown size={13} /> : <ChevronRight size={13} />)
          : <span style={{ width: 13 }} />
        }
        <span className="tree-item-icon">
          {isDir ? <Folder size={13} style={{ color: '#fbbf24' }} /> : <FileCode2 size={13} style={{ color: '#60a5fa' }} />}
        </span>
        <span className="truncate">{node.name}</span>
      </div>
      {isDir && open && node.children?.map(child => (
        <TreeNode key={child.path} node={child} depth={depth + 1} onSelect={onSelect} selectedPath={selectedPath} />
      ))}
    </div>
  )
}

// ─── Project Picker ──────────────────────────────────────────────────────────
function ProjectPicker({ onSelect, settings }) {
  const [input, setInput] = useState('')
  const [recents, setRecents] = useState(settings?.recent_projects || [])

  const submit = () => {
    const p = input.trim()
    if (p) onSelect(p)
  }

  return (
    <div className="project-picker">
      <motion.div
        className="project-picker-card"
        initial={{ opacity: 0, y: 20, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.3 }}
      >
        <div className="project-picker-logo">
          <div className="project-picker-logo-icon">🔍</div>
          <div>
            <div className="project-picker-title">FocusTracer</div>
            <div className="project-picker-subtitle">LLM-guided Python debugger</div>
          </div>
        </div>

        <div className="section">
          <label className="label">Open Project Folder</label>
          <div className="input-row">
            <input
              className="input"
              placeholder="C:\path\to\your\project"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && submit()}
            />
            <button className="btn btn-primary" onClick={submit}>
              <FolderOpen size={14} /> Open
            </button>
          </div>
        </div>

        {recents.length > 0 && (
          <div className="section">
            <label className="label">Recent Projects</label>
            <div className="recents-list">
              {recents.slice(0, 6).map(p => (
                <div key={p} className="recent-item" onClick={() => onSelect(p)}>
                  <Folder size={13} style={{ color: '#fbbf24', flexShrink: 0 }} />
                  <span className="recent-item-path truncate">{p}</span>
                  <ChevronRight size={12} />
                </div>
              ))}
            </div>
          </div>
        )}
      </motion.div>
    </div>
  )
}

// ─── Settings Modal ──────────────────────────────────────────────────────────
function SettingsModal({ onClose, settings, onSave }) {
  const [form, setForm] = useState({ ...settings })
  const [agentStatus, setAgentStatus] = useState(null)
  const [checking, setChecking] = useState(false)
  const [activeTab, setActiveTab] = useState('agent') // 'agent' | 'hardware' | 'metrics'
  const [sysInfo, setSysInfo] = useState(null)
  const [sysLoading, setSysLoading] = useState(false)
  const [metrics, setMetrics] = useState(null)
  const [metricsLoading, setMetricsLoading] = useState(false)

  const checkAgents = async () => {
    setChecking(true)
    try { setAgentStatus(await api.agentsStatus()) } catch { setAgentStatus(null) }
    setChecking(false)
  }

  const loadSysInfo = async () => {
    setSysLoading(true)
    try { setSysInfo(await api.systemInfo()) } catch { setSysInfo(null) }
    setSysLoading(false)
  }

  const loadMetrics = async () => {
    setMetricsLoading(true)
    try { setMetrics(await api.ollamaMetrics(form.model)) } catch { setMetrics(null) }
    setMetricsLoading(false)
  }

  useEffect(() => { checkAgents() }, [])
  useEffect(() => { if (activeTab === 'hardware' && !sysInfo) loadSysInfo() }, [activeTab, sysInfo])
  useEffect(() => { if (activeTab === 'metrics') loadMetrics() }, [activeTab])

  const save = async () => {
    const saved = await api.saveSettings(form)
    onSave(saved)
    onClose()
  }

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  return (
    <div className="settings-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <motion.div
        className="settings-modal"
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        transition={{ duration: 0.2 }}
      >
        <div className="settings-header">
          <div className="settings-title"><Settings size={16} /> Settings</div>
          <button className="btn btn-ghost" style={{ padding: '4px' }} onClick={onClose}><X size={16} /></button>
        </div>

        {/* Tabs */}
        <div className="settings-tabs">
          <button className={`settings-tab ${activeTab === 'agent' ? 'active' : ''}`} onClick={() => setActiveTab('agent')}>
            <Cpu size={12} /> AI Agent
          </button>
          <button className={`settings-tab ${activeTab === 'hardware' ? 'active' : ''}`} onClick={() => setActiveTab('hardware')}>
            <Server size={12} /> Hardware
          </button>
          <button className={`settings-tab ${activeTab === 'metrics' ? 'active' : ''}`} onClick={() => setActiveTab('metrics')}>
            <Gauge size={12} /> Metrics
          </button>
        </div>

        <div className="settings-body">
          {/* ── Agent Tab ── */}
          {activeTab === 'agent' && (
            <>
              <div className="section">
                <label className="label">Default Agent</label>
                <select className="input" value={form.agent} onChange={e => set('agent', e.target.value)}>
                  <option value="ollama">Ollama (Local)</option>
                  <option value="opencode">OpenCode</option>
                </select>
              </div>

              <div className="section">
                <label className="label">Model Name</label>
                <input className="input" value={form.model} onChange={e => set('model', e.target.value)}
                  placeholder={form.agent === 'opencode' ? 'e.g. opencode/minimax-m2.5-free' : 'e.g. qwen2.5:3b'} />
              </div>

              {form.agent === 'ollama' && (
                <div className="section">
                  <label className="label">Ollama URL</label>
                  <input className="input" value={form.ollama_url} onChange={e => set('ollama_url', e.target.value)}
                    placeholder="http://localhost:11434" />
                </div>
              )}

              {form.agent === 'opencode' && (
                <div className="section">
                  <label className="label">OpenCode Command</label>
                  <input className="input" value={form.opencode_cmd} onChange={e => set('opencode_cmd', e.target.value)}
                    placeholder="opencode" />
                </div>
              )}

              <div className="section">
                <div className="flex items-center justify-between" style={{ marginBottom: 6 }}>
                  <label className="label" style={{ marginBottom: 0 }}>Agent Status</label>
                  <button className="btn btn-ghost" style={{ padding: '2px 8px', fontSize: 11 }} onClick={checkAgents}>
                    {checking ? <Loader2 size={12} className="spinning" /> : <RefreshCw size={12} />} Refresh
                  </button>
                </div>
                {agentStatus ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {['ollama', 'opencode'].map(agent => {
                      const st = agentStatus[agent]
                      return (
                        <div key={agent} className="agent-status-row">
                          <span className="agent-status-name">{agent === 'ollama' ? 'Ollama' : 'OpenCode'}</span>
                          {st?.ok
                            ? <span className="badge badge-success"><CheckCircle2 size={10} /> Online</span>
                            : <span className="badge badge-error"><XCircle size={10} /> Offline</span>
                          }
                          {st?.ok && st?.model_available !== undefined && (
                            st.model_available
                              ? <span className="badge badge-info">Model ✓</span>
                              : <span className="badge badge-warning">Model missing</span>
                          )}
                          {st?.version && <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>v{st.version}</span>}
                        </div>
                      )
                    })}
                  </div>
                ) : <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading…</div>}
              </div>
            </>
          )}

          {/* ── Hardware Tab ── */}
          {activeTab === 'hardware' && (
            <div className="hw-panel">
              {sysLoading && <div className="flex items-center gap-2" style={{ color: 'var(--text-muted)', padding: 8 }}><div className="spinner" /> Loading hardware info…</div>}
              {!sysLoading && !sysInfo && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Failed to load hardware info.</div>}
              {sysInfo && (
                <>
                  <div className="hw-section">
                    <div className="hw-section-title"><Cpu size={12} /> CPU</div>
                    <div className="hw-row"><span>Model</span><span className="hw-val">{sysInfo.cpu?.name || '—'}</span></div>
                    <div className="hw-row"><span>Cores</span><span className="hw-val">{sysInfo.cpu?.cores_physical ?? '—'} physical / {sysInfo.cpu?.cores_logical ?? '—'} logical</span></div>
                    {sysInfo.cpu?.freq_mhz && <div className="hw-row"><span>Frequency</span><span className="hw-val">{sysInfo.cpu.freq_mhz} MHz</span></div>}
                    {sysInfo.cpu?.usage_percent != null && (
                      <div className="hw-row">
                        <span>Usage</span>
                        <span className="hw-val">
                          <div className="hw-bar-wrap"><div className="hw-bar" style={{ width: `${sysInfo.cpu.usage_percent}%`, background: 'var(--accent-cyan)' }} /></div>
                          {sysInfo.cpu.usage_percent}%
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="hw-section">
                    <div className="hw-section-title"><Server size={12} /> Memory (RAM)</div>
                    {sysInfo.memory?.total_gb != null ? (
                      <>
                        <div className="hw-row"><span>Total</span><span className="hw-val">{sysInfo.memory.total_gb} GB</span></div>
                        <div className="hw-row"><span>Available</span><span className="hw-val">{sysInfo.memory.available_gb} GB</span></div>
                        <div className="hw-row">
                          <span>Used</span>
                          <span className="hw-val">
                            <div className="hw-bar-wrap"><div className="hw-bar" style={{ width: `${sysInfo.memory.used_percent}%`, background: sysInfo.memory.used_percent > 80 ? 'var(--accent-red)' : 'var(--accent-green)' }} /></div>
                            {sysInfo.memory.used_percent}%
                          </span>
                        </div>
                      </>
                    ) : <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Install psutil for RAM info: <code>pip install psutil</code></div>}
                  </div>

                  <div className="hw-section">
                    <div className="hw-section-title"><Flame size={12} /> GPU</div>
                    {sysInfo.gpu.length === 0
                      ? <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No GPU detected. Install GPUtil: <code>pip install GPUtil</code></div>
                      : sysInfo.gpu.map((g, i) => (
                        <div key={i}>
                          <div className="hw-row"><span>Name</span><span className="hw-val">{g.name}</span></div>
                          {g.vram_total_mb && <div className="hw-row"><span>VRAM</span><span className="hw-val">{g.vram_used_mb}/{g.vram_total_mb} MB</span></div>}
                          {g.load_percent != null && (
                            <div className="hw-row">
                              <span>Load</span>
                              <span className="hw-val">
                                <div className="hw-bar-wrap"><div className="hw-bar" style={{ width: `${g.load_percent}%`, background: 'var(--accent-purple)' }} /></div>
                                {g.load_percent}%
                              </span>
                            </div>
                          )}
                          {g.temperature_c && <div className="hw-row"><span>Temp</span><span className="hw-val">{g.temperature_c}°C</span></div>}
                        </div>
                      ))
                    }
                  </div>

                  <div className="hw-section">
                    <div className="hw-section-title"><Activity size={12} /> System</div>
                    <div className="hw-row"><span>Platform</span><span className="hw-val hw-val-sm">{sysInfo.platform}</span></div>
                    <div className="hw-row"><span>Python</span><span className="hw-val">{sysInfo.python}</span></div>
                  </div>
                </>
              )}
              <button className="btn btn-ghost" style={{ fontSize: 11, marginTop: 8 }} onClick={loadSysInfo}>
                <RefreshCw size={11} /> Refresh
              </button>
            </div>
          )}

          {/* ── Metrics Tab ── */}
          {activeTab === 'metrics' && (
            <div className="hw-panel">
              {form.agent !== 'ollama' && (
                <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '8px 0' }}>
                  Metrics are only available for local Ollama models.
                </div>
              )}
              {form.agent === 'ollama' && (
                <>
                  {metricsLoading && <div className="flex items-center gap-2" style={{ color: 'var(--text-muted)', padding: 8 }}><div className="spinner" /> Running benchmark (a few tokens)…</div>}
                  {!metricsLoading && metrics?.error && <div style={{ color: 'var(--accent-red)', fontSize: 12 }}>Error: {metrics.error}</div>}
                  {!metricsLoading && metrics && !metrics.error && (
                    <>
                      <div className="hw-section">
                        <div className="hw-section-title"><Gauge size={12} /> Model Performance — {metrics.model}</div>
                        <div className="hw-row">
                          <span>Generation speed</span>
                          <span className="hw-val metric-highlight">{metrics.tokens_per_sec} tok/s</span>
                        </div>
                        <div className="hw-row">
                          <span>Prompt processing</span>
                          <span className="hw-val">{metrics.prompt_tokens_per_sec} tok/s</span>
                        </div>
                        <div className="hw-row"><span>Total benchmark time</span><span className="hw-val">{metrics.total_duration_ms} ms</span></div>
                      </div>

                      <div className="hw-section">
                        <div className="hw-section-title"><Flame size={12} /> Energy Estimate</div>
                        <div className="hw-row">
                          <span>Per benchmark run</span>
                          <span className="hw-val metric-highlight">{metrics.energy_j_estimate != null ? `${metrics.energy_j_estimate} J` : '—'}</span>
                        </div>
                        <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 4 }}>{metrics.energy_note}</div>
                      </div>
                    </>
                  )}
                  <button className="btn btn-ghost" style={{ fontSize: 11, marginTop: 8 }} onClick={loadMetrics} disabled={metricsLoading}>
                    {metricsLoading ? <><Loader2 size={11} className="spinning" /> Running…</> : <><RefreshCw size={11} /> Re-run Benchmark</>}
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        <div className="settings-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={save}>Save Settings</button>
        </div>
      </motion.div>
    </div>
  )
}

// ─── XML Viewer Modal ────────────────────────────────────────────────────────
function XmlModal({ file, onClose }) {
  const [content, setContent] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.getOutput(file.path).then(d => { setContent(d.content); setLoading(false) }).catch(() => setLoading(false))
  }, [file])

  return (
    <div className="xml-modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <motion.div
        className="xml-modal"
        initial={{ opacity: 0, scale: 0.95, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95 }}
        transition={{ duration: 0.2 }}
      >
        <div className="xml-modal-header">
          <div className="xml-modal-title">
            <FileText size={14} style={{ color: 'var(--accent-cyan)' }} />
            {file.filename}
            <span className="badge badge-neutral">{(file.size / 1024).toFixed(1)} KB</span>
          </div>
          <button className="btn btn-ghost" style={{ padding: '4px' }} onClick={onClose}><X size={16} /></button>
        </div>
        <div className="xml-modal-body">
          {loading
            ? <div className="flex items-center gap-2" style={{ color: 'var(--text-muted)' }}><div className="spinner" /> Loading…</div>
            : <pre className="xml-content">{content || 'Empty file'}</pre>
          }
        </div>
      </motion.div>
    </div>
  )
}

// ─── TraceConfig Panel ───────────────────────────────────────────────────────
function TraceConfigPanel({ projectRoot, targetScript, settings, onJobStart }) {
  const [mode, setMode] = useState('manual') // 'manual' | 'auto'
  const [functions, setFunctions] = useState([])
  const [hint, setHint] = useState('')
  const [errorCtx, setErrorCtx] = useState('')
  const [outputDir, setOutputDir] = useState('output')
  const [detail, setDetail] = useState('detailed')
  const [inventory, setInventory] = useState(null)
  const [running, setRunning] = useState(false)
  const [jobStatus, setJobStatus] = useState(null) // null | 'done' | 'error'

  // Load inventory when script changes
  useEffect(() => {
    if (!projectRoot || !targetScript) { setInventory(null); return }
    api.getInventory(projectRoot, targetScript)
      .then(setInventory)
      .catch(() => setInventory(null))
  }, [projectRoot, targetScript])

  const toggleFn = (fn) => {
    setFunctions(prev => prev.includes(fn) ? prev.filter(f => f !== fn) : [...prev, fn])
  }

  const run = async () => {
    if (!targetScript) return
    setRunning(true)
    setJobStatus(null)

    const absOutputDir = outputDir.startsWith('.')
      ? `${projectRoot}/${outputDir}`.replace(/\\/g, '/')
      : outputDir

    try {
      let res
      if (mode === 'manual') {
        res = await api.runTrace({
          project_root: projectRoot,
          target_script: targetScript,
          functions,
          output_dir: absOutputDir,
          detail,
        })
      } else {
        res = await api.suggestTrace({
          project_root: projectRoot,
          target_script: targetScript,
          hint: hint || null,
          error_context: errorCtx || null,
          execute: true,
          output_dir: absOutputDir,
          detail,
          functions,
        })
      }
      onJobStart(res.job_id, () => { setRunning(false) })
    } catch (err) {
      setRunning(false)
      setJobStatus('error')
    }
  }

  const hasScript = !!targetScript
  const canRun = hasScript && (mode === 'auto' || functions.length > 0)

  return (
    <div className="right-panel">
      <div className="right-panel-header">
        <div className="right-panel-title"><Activity size={13} /> Trace Config</div>
        {targetScript && (
          <span className="badge badge-info" style={{ fontSize: 10 }}>
            {targetScript.split(/[\\/]/).pop()}
          </span>
        )}
      </div>
      <div className="right-panel-body">
        {/* Mode selector */}
        <div className="section">
          <div className="section-title">Mode</div>
          <div className="mode-tabs">
            <button className={`mode-tab ${mode === 'manual' ? 'active' : ''}`} onClick={() => setMode('manual')}>
              <Terminal size={13} /> Manual
            </button>
            <button className={`mode-tab ${mode === 'auto' ? 'active' : ''}`} onClick={() => setMode('auto')}>
              <Zap size={13} /> AI Suggest
            </button>
          </div>
        </div>

        {/* Target script display */}
        <div className="section">
          <div className="section-title"><FileCode2 size={11} /> Target Script</div>
          {targetScript
            ? <div className="status-bar"><FileCode2 size={12} />{targetScript.split(/[\\/]/).pop()}</div>
            : <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>← Select a Python file from the file tree</div>
          }
        </div>

        {/* Manual: function targets */}
        {mode === 'manual' && (
          <>
            <div className="section">
              <div className="section-title">Functions to Trace</div>
              <TagInput
                value={functions}
                onChange={setFunctions}
                placeholder="Type function name + Enter"
              />
            </div>
            {inventory?.functions?.length > 0 && (
              <div className="section">
                <div className="section-title">Available Functions</div>
                <div className="fn-list">
                  {inventory.functions.map(fn => (
                    <div
                      key={fn}
                      className={`fn-item ${functions.includes(fn) ? 'selected' : ''}`}
                      onClick={() => toggleFn(fn)}
                    >
                      <div className="fn-item-check">{functions.includes(fn) ? '✓' : ''}</div>
                      <span className="truncate">{fn}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {/* Auto: hint + error context */}
        {mode === 'auto' && (
          <>
            <div className="section">
              <div className="section-title">Agent: {settings?.agent || 'ollama'} / {settings?.model}</div>
            </div>
            <div className="section">
              <label className="label">Hint (optional)</label>
              <textarea className="input" value={hint} onChange={e => setHint(e.target.value)}
                placeholder="Describe what to trace, e.g. 'focus on the sorting algorithm'" rows={2} />
            </div>
            <div className="section">
              <label className="label">Error Context (optional)</label>
              <textarea className="input" value={errorCtx} onChange={e => setErrorCtx(e.target.value)}
                placeholder="Paste error message or stack trace here..." rows={3} />
            </div>
            {/* Optional manual function additions */}
            <div className="section">
              <label className="label">Also include functions (optional)</label>
              <TagInput value={functions} onChange={setFunctions} placeholder="Extra functions + Enter" />
            </div>
          </>
        )}

        {/* Options */}
        <div className="section">
          <div className="section-title">Options</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ flex: 1 }}>
              <label className="label">Detail Level</label>
              <select className="input" value={detail} onChange={e => setDetail(e.target.value)}>
                <option value="minimal">Minimal</option>
                <option value="normal">Normal</option>
                <option value="detailed">Detailed</option>
              </select>
            </div>
            <div style={{ flex: 1 }}>
              <label className="label">Output Dir</label>
              <input className="input" value={outputDir} onChange={e => setOutputDir(e.target.value)} />
            </div>
          </div>
        </div>

        {/* Run button */}
        <div className="run-section">
          <button
            className={`btn btn-primary run-btn-full ${running ? 'running' : ''}`}
            onClick={run}
            disabled={!canRun || running}
          >
            {running
              ? <><div className="spinner" /> Running…</>
              : mode === 'auto'
                ? <><Zap size={14} /> AI Suggest &amp; Run</>
                : <><Play size={14} /> Run Trace</>
            }
          </button>
          {!hasScript && (
            <div style={{ color: 'var(--text-muted)', fontSize: 11, textAlign: 'center' }}>
              Select a target script first
            </div>
          )}
          {mode === 'manual' && hasScript && functions.length === 0 && (
            <div style={{ color: 'var(--text-muted)', fontSize: 11, textAlign: 'center' }}>
              Add at least one function target
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Log Stream ───────────────────────────────────────────────────────────────
function LogStream({ entries }) {
  const ref = useRef(null)
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight }, [entries])

  if (!entries.length) return (
    <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '8px 4px' }}>
      No active trace. Run a trace to see live output here.
    </div>
  )

  return (
    <div className="log-stream" ref={ref} style={{ maxHeight: 160, overflowY: 'auto' }}>
      {entries.map((e, i) => (
        <div key={i} className={`log-entry ${e.kind || 'info'}`}>
          <span className="log-ts">{e.ts ? e.ts.slice(11, 19) : ''}</span>
          <span className="log-msg">{e.message}</span>
        </div>
      ))}
    </div>
  )
}

// ─── Output List ─────────────────────────────────────────────────────────────
function OutputList({ projectRoot, onView, refreshTrigger }) {
  const [outputs, setOutputs] = useState([])
  const [selected, setSelected] = useState(null)

  const load = useCallback(() => {
    api.listOutputs(projectRoot).then(d => setOutputs(d.outputs || [])).catch(() => {})
  }, [projectRoot])

  useEffect(() => { load() }, [load, refreshTrigger])

  const view = (item) => { setSelected(item.path); onView(item) }

  if (!outputs.length) return (
    <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '8px 4px' }}>
      No trace logs yet. Run a trace to generate output.
    </div>
  )

  return (
    <div className="output-list">
      {outputs.map(item => (
        <motion.div
          key={item.path}
          className={`output-item ${selected === item.path ? 'active' : ''}`}
          onClick={() => view(item)}
          initial={{ opacity: 0, x: -4 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.15 }}
        >
          <FileText size={13} style={{ color: 'var(--accent-cyan)', flexShrink: 0 }} />
          <span className="output-item-name truncate">{item.filename}</span>
          <span className="output-item-size">{(item.size / 1024).toFixed(1)} KB</span>
          <span className="output-item-meta">{item.modified?.slice(0, 10)}</span>
          <Eye size={12} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
        </motion.div>
      ))}
    </div>
  )
}

// ─── Bottom Panel ─────────────────────────────────────────────────────────────
function BottomPanel({ logEntries, projectRoot, refreshTrigger }) {
  const [tab, setTab] = useState('log')
  const [viewFile, setViewFile] = useState(null)

  return (
    <div className="bottom-panel">
      <div className="bottom-tabs">
        <div className={`bottom-tab ${tab === 'log' ? 'active' : ''}`} onClick={() => setTab('log')}>
          <Terminal size={12} /> Live Output
          {logEntries.length > 0 && (
            <span className="badge badge-info" style={{ padding: '1px 5px', fontSize: 10 }}>{logEntries.length}</span>
          )}
        </div>
        <div className={`bottom-tab ${tab === 'outputs' ? 'active' : ''}`} onClick={() => setTab('outputs')}>
          <Download size={12} /> Trace Logs
        </div>
        <div style={{ flex: 1 }} />
        {tab === 'outputs' && (
          <button className="btn btn-ghost" style={{ padding: '4px 8px', fontSize: 11 }} onClick={() => setTab('outputs')}>
            <RefreshCw size={11} /> Refresh
          </button>
        )}
      </div>
      <div className="bottom-content">
        {tab === 'log' && <LogStream entries={logEntries} />}
        {tab === 'outputs' && (
          <OutputList projectRoot={projectRoot} onView={setViewFile} refreshTrigger={refreshTrigger} />
        )}
      </div>

      <AnimatePresence>
        {viewFile && <XmlModal file={viewFile} onClose={() => setViewFile(null)} />}
      </AnimatePresence>
    </div>
  )
}

// ─── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [settings, setSettings] = useState(null)
  const [projectRoot, setProjectRoot] = useState(null)
  const [fileTree, setFileTree] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [fileContent, setFileContent] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const [logEntries, setLogEntries] = useState([])
  const [outputRefresh, setOutputRefresh] = useState(0)
  const unsubRef = useRef(null)

  // Load settings on mount
  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => setSettings({}))
  }, [])

  // Load file tree when project changes
  useEffect(() => {
    if (!projectRoot) { setFileTree([]); return }
    api.listFiles(projectRoot)
      .then(d => setFileTree(d.tree || []))
      .catch(() => setFileTree([]))
  }, [projectRoot])

  // Load file content when selection changes
  useEffect(() => {
    if (!selectedFile) { setFileContent(null); return }
    api.fileContent(selectedFile.path)
      .then(d => setFileContent(d.content))
      .catch(() => setFileContent('// Error loading file'))
  }, [selectedFile])

  const handleFileSelect = (node) => setSelectedFile(node)

  const handleJobStart = (jobId, onComplete) => {
    setLogEntries([])
    if (unsubRef.current) unsubRef.current()

    const unsub = subscribeJobStream(
      jobId,
      (entry) => setLogEntries(prev => [...prev, entry]),
      (status, result) => {
        setLogEntries(prev => [...prev, {
          kind: status === 'done' ? 'success' : 'error',
          message: status === 'done'
            ? `✅ Done! ${result?.filename || ''}`
            : '❌ Trace failed.',
          ts: new Date().toISOString(),
        }])
        setOutputRefresh(r => r + 1)
        onComplete()
      }
    )
    unsubRef.current = unsub
  }

  // Initial: show project picker if no project
  if (!settings) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: 'var(--text-muted)' }}>
      <div className="spinner" style={{ width: 24, height: 24 }} />
    </div>
  }

  if (!projectRoot) {
    return (
      <>
        <ProjectPicker settings={settings} onSelect={setProjectRoot} />
        <AnimatePresence>
          {showSettings && (
            <SettingsModal settings={settings} onClose={() => setShowSettings(false)} onSave={setSettings} />
          )}
        </AnimatePresence>
      </>
    )
  }

  const projectName = projectRoot.split(/[\\/]/).pop()

  return (
    <div className="app-layout">
      {/* TopBar */}
      <header className="topbar">
        <div className="topbar-logo">
          <div className="topbar-logo-icon">🔍</div>
          <span className="topbar-logo-name">FocusTracer</span>
          <span className="topbar-subtitle">v1.0</span>
        </div>
        <div className="topbar-project">
          <Folder size={12} style={{ color: '#fbbf24', flexShrink: 0 }} />
          <span className="topbar-project-path truncate">{projectName}</span>
          <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{projectRoot}</span>
        </div>
        <div className="topbar-actions">
          <button className="btn btn-ghost" onClick={() => setProjectRoot(null)} title="Change project">
            <FolderOpen size={14} />
          </button>
          <button className="btn btn-ghost" onClick={() => setShowSettings(true)} title="Settings">
            <Settings size={14} />
          </button>
        </div>
      </header>

      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <span className="sidebar-title">Files</span>
          <button className="btn btn-ghost" style={{ padding: '2px' }}
            onClick={() => api.listFiles(projectRoot).then(d => setFileTree(d.tree || []))}>
            <RefreshCw size={12} />
          </button>
        </div>
        <div className="sidebar-tree">
          {fileTree.length === 0
            ? <div style={{ padding: '12px 14px', color: 'var(--text-muted)', fontSize: 12 }}>No Python files found.</div>
            : fileTree.map(node => (
              <TreeNode key={node.path} node={node} depth={0} onSelect={handleFileSelect} selectedPath={selectedFile?.path} />
            ))
          }
        </div>
      </aside>

      {/* Code Viewer */}
      <main className="code-area">
        <div className="code-area-header">
          {selectedFile && (
            <div className={`code-tab active`}>
              <FileCode2 size={12} /> {selectedFile.name}
            </div>
          )}
        </div>
        {selectedFile && fileContent !== null ? (
          <CodeMirror
            value={fileContent}
            extensions={[python()]}
            theme={oneDark}
            readOnly
            style={{ flex: 1, overflow: 'auto', fontSize: 13, fontFamily: "'JetBrains Mono', monospace" }}
            basicSetup={{ lineNumbers: true, foldGutter: true, highlightActiveLine: true }}
          />
        ) : (
          <div className="code-empty">
            <div className="code-empty-icon">📄</div>
            <div style={{ font: '14px Inter, sans-serif', color: 'var(--text-muted)' }}>
              Select a Python file to view its contents
            </div>
            {selectedFile && <div className="spinner" />}
          </div>
        )}
      </main>

      {/* Right: Trace Config */}
      <TraceConfigPanel
        projectRoot={projectRoot}
        targetScript={selectedFile?.path || null}
        settings={settings}
        onJobStart={handleJobStart}
      />

      {/* Bottom Panel */}
      <BottomPanel
        logEntries={logEntries}
        projectRoot={projectRoot}
        refreshTrigger={outputRefresh}
      />

      {/* Modals */}
      <AnimatePresence>
        {showSettings && (
          <SettingsModal settings={settings} onClose={() => setShowSettings(false)} onSave={setSettings} />
        )}
      </AnimatePresence>
    </div>
  )
}
