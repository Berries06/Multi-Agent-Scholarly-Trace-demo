import type {
  Domain,
  GraphData,
  Health,
  IngestResult,
  LearnerProfile,
  RunResult,
} from './types'

const jsonHeaders = { 'Content-Type': 'application/json' }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`${response.status} ${response.statusText}: ${detail}`)
  }
  return response.json() as Promise<T>
}

export function getHealth(): Promise<Health> {
  return request('/api/health')
}

export function getProfiles(): Promise<LearnerProfile[]> {
  return request('/api/profiles')
}

export function getDomains(): Promise<Domain[]> {
  return request('/api/domains')
}

export function getExtractedGraph(domainId?: string | null): Promise<GraphData> {
  const suffix = domainId ? `?domain_id=${encodeURIComponent(domainId)}` : ''
  return request(`/api/extracted-graph${suffix}`)
}

export interface RunPayload {
  profile_id: string
  query: string
  domain_id?: string | null
  include_ablation?: boolean
}

export function runPipeline(payload: RunPayload): Promise<RunResult> {
  return request('/api/run', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export interface IngestPayload {
  paper_id: string
  title: string
  text: string
  profile_id: string
  accept_threshold: number
}

export function ingestPaper(payload: IngestPayload): Promise<IngestResult> {
  return request('/api/ingest-paper', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}
