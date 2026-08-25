export interface Health {
  status: string
  service: string
  domain_count: number
  profile_count: number
  core_agents: number
  system_agents: number
}

export interface UserAccount {
  user_id: string
  email: string
  nickname: string
  profile_version: number
  profile: LearnerProfile
}

export interface AuthState {
  authenticated: boolean
  user: UserAccount | null
}

export interface ProviderOption {
  id: string
  label: string
  description: string
  default_model: string
  models: string[]
  requires_api_key: boolean
  access_mode: 'offline' | 'free' | 'byok'
  available: boolean
}

export interface LearnerProfile {
  profile_id: string
  name: string
  persona: string
  education: string
  role: string
  goal: string
  interests: string[]
  knowledge_scores: Record<string, number>
  preferred_style: string
  expected_difficulty: number
  synthetic: boolean
  profile_kind?: 'personal' | 'demo'
  required_concepts?: string[]
}

export interface Domain {
  domain_id: string
  domain_name: string
  paper_count: number
  evidence_paper_count: number
  metadata_only_paper_count: number
  query_example?: string
  description?: string
  [key: string]: unknown
}

export interface ExperimentProtocol {
  slug: string
  title: string
  purpose: string
  mode: string
  evaluation_type: string
  claim_ceiling: string
  primary_metrics: string[]
  config_path: string
}

export interface ExperimentRun {
  run_id: string
  artifact_path: string
  experiment: string
  title: string
  generated_at: string | null
  status: string
  evaluation_type: string
  claim_ceiling: string
  git_head: string | null
  git_dirty: boolean | null
  summary: Array<Record<string, unknown>>
  error?: string
}

export interface ExperimentLedger {
  schema_version: string
  protocol_count: number
  run_count: number
  run_command: string
  mlflow_url: string
  protocols: ExperimentProtocol[]
  runs: ExperimentRun[]
}

export interface AgentTraceStep {
  agent: string
  role: string
  status: string
  summary: string
  duration_ms?: number
  details?: Record<string, unknown>
}

export interface Diagnosis {
  readiness_score: number
  blind_spots: string[]
  strengths: string[]
  target_difficulty: number
  resource_match_score: number
  difficulty_curve: Array<{ stage: string; difficulty: number }>
  learning_path: string[]
}

export interface Claim {
  claim_id: string
  source: string
  relation: string
  target: string
  relation_type: string
  status: string
  judge_score: number
  criticisms: string[]
  evidence_ids: string[]
}

export interface Resources {
  briefing: {
    title: string
    level: number
    strategy: string
    sections: unknown[]
    citations: string[]
  }
  practical_guide: { title: string; estimated_minutes: number; steps: unknown[] }
  quiz: { title: string; items: unknown[] }
  blue_ocean: { hypothesis: string; caveat: string; evidence_ids: string[] }
  covered_concepts: string[]
}

export interface RunResult {
  run_id?: string
  profile: LearnerProfile
  diagnosis: Diagnosis
  agent_trace: AgentTraceStep[]
  specialist_agent_trace: AgentTraceStep[]
  claims: Claim[]
  resources: Resources
  metrics: {
    hallucination_proxy_rate: number
    adaptation_accuracy: number
    knowledge_coverage_rate: number
    accepted_claims: number
    rejected_claims: number
  }
  report: {
    blind_spots: string[]
    difficulty_curve: unknown[]
    learning_path: string[]
    resource_match_score: number
  }
  evidence_details?: Record<string, EvidenceSpan[]>
  ablation?: { variants: unknown[] }
  provider_run?: {
    provider?: string
    provider_label?: string
    model?: string
    access_mode?: string
    mode?: string
    source_mode?: string
    usage?: { input_tokens: number; output_tokens: number; total_tokens: number }
    warnings?: string[]
    api_key_persisted?: boolean
  }
  graph_insights?: {
    timeline?: Array<Record<string, unknown>>
    research_ideas?: Array<Record<string, unknown>>
    [key: string]: unknown
  }
  graph_retrieval?: Record<string, unknown>
  persistence?: {
    saved: boolean
    research_session_id?: string
    ingestion_id?: string
    source_saved?: boolean
  }
  feedback?: { decision?: string }
}

// —— 实验台（粘贴论文）返回结构 ——

export interface EntityMention {
  mention_id: string
  entity_id: string
  surface_form: string
  evidence_id: string
  char_start: number
  char_end: number
}

export interface ExtractedEntity {
  entity_id: string
  canonical_name: string
  entity_type: string
  aliases: string[]
  mentions: EntityMention[]
  confidence: number
}

export interface ExtractedRelation {
  relation_id: string
  source_id: string
  target_id: string
  relation_type: string
  evidence_ids: string[]
  confidence: number
  status: string
  criticisms: string[]
  extraction_method: string
}

export interface EvidenceSpan {
  evidence_id: string
  paper_id: string
  section_id: string
  sentence_index: number
  text: string
  char_start: number
  char_end: number
}

export interface ExtractionResult {
  schema_version: string
  papers: unknown[]
  entities: ExtractedEntity[]
  relations: ExtractedRelation[]
  evidence: EvidenceSpan[]
  communities: unknown[]
  audit: Record<string, unknown>
  graph: { nodes: unknown[]; edges: unknown[] }
}

export interface DecisionClaim {
  claim_id: string
  source: string
  relation: string
  target: string
  relation_type: string
  base_confidence: number
  source_type: string
  target_type: string
  evidence_ids: string[]
  criticisms: string[]
  proposal_reason: string
  judge_reason: string
  judge_score: number
  status: string
}

export interface IngestSummary {
  entity_count: number
  candidate_relation_count: number
  claim_count: number
  accepted_count: number
  rejected_count: number
  needs_review_count: number
  accepted_without_evidence_count: number
}

export interface IngestResult {
  fingerprint: {
    paper_id: string
    title: string
    text_char_count: number
    accept_threshold: number
    profile_id: string
    schema_version: string
  }
  document: { paper_id: string; title: string; sections: Record<string, string> }
  extraction: ExtractionResult
  diagnosis: Diagnosis
  proposed_claims: DecisionClaim[]
  critiqued_claims: DecisionClaim[]
  adjudicated_claims: DecisionClaim[]
  agent_trace: AgentTraceStep[]
  specialist_agent_trace: AgentTraceStep[]
  resources: Resources
  summary: IngestSummary
}

// —— 证据知识图谱（/api/extracted-graph）——

export interface GraphNode {
  id: string
  label: string
  kind: string
  confidence?: number
  source_url?: string
  paper_id?: string
  section_id?: string
  char_start?: number
  char_end?: number
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  label: string
  status?: string
  confidence?: number
  evidence_ids?: string[]
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}
