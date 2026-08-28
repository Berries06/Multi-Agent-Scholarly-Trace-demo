import type {
  AgentTraceStep,
  AuthState,
  Domain,
  ExperimentLedger,
  GraphData,
  Health,
  IngestResult,
  LearnerProfile,
  ProviderOption,
  ResearchProgressEvent,
  RunResult,
  UserAccount,
} from './types'

const jsonHeaders = { 'Content-Type': 'application/json; charset=utf-8' }
const apiPrefix = window.location.pathname.startsWith('/AgentDemo/start') ? '/AgentDemo/start/api' : '/api'
const apiPath = (path: string) => path.replace(/^\/api/, apiPrefix)

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiPath(path), { credentials: 'include', ...init })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null
    throw new Error(payload?.error?.message || `${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

export const getHealth = (): Promise<Health> => request('/api/health')
export const getAuth = (): Promise<AuthState> => request('/api/auth/me')
export const login = (identifier: string, password: string): Promise<AuthState> =>
  request('/api/auth/login', { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ identifier, password }) })
export const logout = (): Promise<AuthState> => request('/api/auth/logout', { method: 'POST' })
export const updateProfile = (profile: LearnerProfile): Promise<{ profile: LearnerProfile } & UserAccount> =>
  request('/api/me/profile', { method: 'PUT', headers: jsonHeaders, body: JSON.stringify(profile) })

export const getProfiles = (): Promise<LearnerProfile[]> => request('/api/profiles')
export const getDomains = (): Promise<Domain[]> => request('/api/domains')
export const getProviders = (): Promise<ProviderOption[]> => request('/api/providers')
export const getExperimentLedger = (): Promise<ExperimentLedger> => request('/api/experiments')
export const getHistory = (): Promise<Array<Record<string, unknown>>> => request('/api/history')
export const getIngestions = (): Promise<Array<Record<string, unknown>>> => request('/api/ingestions')

export function getExtractedGraph(domainId?: string | null): Promise<GraphData> {
  const suffix = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : ''
  return request<GraphData | { graph: GraphData }>(`/api/extracted-graph${suffix}`)
    .then((payload) => ('graph' in payload ? payload.graph : payload))
}

export interface ProviderPayload {
  provider: string
  model?: string
  api_key?: string
  timeout_seconds?: number
}

export interface RunPayload {
  profile_id: string
  query: string
  domain_id?: string | null
  include_ablation?: boolean
  llm: ProviderPayload
}

export const runPipeline = (payload: RunPayload): Promise<RunResult> =>
  request('/api/run', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export async function streamPipeline(
  payload: RunPayload,
  handlers: {
    onStarted?: (operationId: string) => void
    onStep?: (step: AgentTraceStep) => void
    onProgress?: (progress: ResearchProgressEvent) => void
    onHeartbeat?: (elapsedMs: number) => void
  },
): Promise<RunResult> {
  const response = await fetch(apiPath('/api/run/stream'), {
    method: 'POST', credentials: 'include', headers: { ...jsonHeaders, Accept: 'text/event-stream' }, body: JSON.stringify(payload),
  })
  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => null) as { error?: { message?: string } } | null
    throw new Error(error?.error?.message || `流式运行失败（HTTP ${response.status}）`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: RunResult | null = null
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const event = block.match(/^event:\s*(.+)$/m)?.[1]
      const raw = block.match(/^data:\s*(.+)$/m)?.[1]
      if (!event || !raw) continue
      const data = JSON.parse(raw) as Record<string, unknown>
      if (event === 'started') handlers.onStarted?.(String(data.operation_id ?? ''))
      if (event === 'agent_step') handlers.onStep?.(data.step as AgentTraceStep)
      if (event === 'progress') handlers.onProgress?.(data.progress as ResearchProgressEvent)
      if (event === 'heartbeat') handlers.onHeartbeat?.(Number(data.elapsed_ms ?? 0))
      if (event === 'error') throw new Error(String(data.message ?? '运行中断'))
      if (event === 'completed') result = data.result as RunResult
    }
    if (done) break
  }
  if (!result) throw new Error('运行流已结束，但没有收到完成结果。')
  return result
}

export const testProvider = (payload: ProviderPayload): Promise<Record<string, unknown>> =>
  request('/api/providers/test', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export const sendFeedback = (payload: {
  profile_id: string; query: string; domain_id?: string | null; feedback: 'too_hard' | 'suitable' | 'too_easy'
}): Promise<RunResult> => request('/api/feedback', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export const searchOnline = (payload: { query: string; limit?: number; allow_network: boolean }): Promise<Record<string, unknown>> =>
  request('/api/online-rag', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export const queryGraph = (payload: { query: string; domain_id?: string | null }): Promise<Record<string, unknown>> =>
  request('/api/graph-query', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export interface IngestPayload {
  paper_id: string
  title: string
  text: string
  profile_id: string
  accept_threshold: number
  save_source?: boolean
}

export const ingestPaper = (payload: IngestPayload): Promise<IngestResult> =>
  request('/api/ingest-paper', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) })

export function ingestPdf(payload: {
  file: File; profile_id: string; paper_id: string; title: string; accept_threshold: number; save_source?: boolean
}): Promise<IngestResult> {
  const form = new FormData()
  form.append('file', payload.file)
  form.append('profile_id', payload.profile_id)
  form.append('paper_id', payload.paper_id)
  form.append('title', payload.title)
  form.append('accept_threshold', String(payload.accept_threshold))
  form.append('save_source', String(payload.save_source ?? false))
  return request('/api/ingest-pdf', { method: 'POST', body: form })
}
