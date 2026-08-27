import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Input,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from 'antd'
import AgentTrace from './AgentTrace'
import DiagnosisRadar from './DiagnosisRadar'
import KnowledgeGraphView from './KnowledgeGraphView'
import LlmModelSelector from './LlmModelSelector'
import { getDomains, getExtractedGraph, getProfiles, runPipeline } from './api'
import type {
  Domain,
  GraphData,
  LearnerProfile,
  LlmConfig,
  RunResult,
} from './types'

const { Text, Paragraph } = Typography

function statusTag(status: string) {
  if (status === 'accepted') return <Tag color="green">accepted</Tag>
  if (status === 'rejected') return <Tag color="red">rejected</Tag>
  return <Tag color="orange">needs_review</Tag>
}

export default function ProductPage() {
  const [domains, setDomains] = useState<Domain[]>([])
  const [profiles, setProfiles] = useState<LearnerProfile[]>([])
  const [domainId, setDomainId] = useState<string | undefined>()
  const [profileId, setProfileId] = useState<string | undefined>()
  const [query, setQuery] = useState('')
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null)
  const [result, setResult] = useState<RunResult | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([getDomains(), getProfiles()])
      .then(([domainsData, profilesData]) => {
        if (cancelled) return
        setDomains(domainsData)
        setProfiles(profilesData)
        setDomainId(domainsData[0]?.domain_id)
        setProfileId(profilesData[0]?.profile_id)
        const example = domainsData[0]?.query_example
        if (typeof example === 'string') setQuery(example)
      })
      .catch((err: Error) => setError(err.message))
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    getExtractedGraph(domainId ?? null)
      .then((data) => {
        if (!cancelled) setGraph(data)
      })
      .catch(() => {
        if (!cancelled) setGraph(null)
      })
    return () => {
      cancelled = true
    }
  }, [domainId])

  const domainOptions = useMemo(
    () => domains.map((d) => ({ value: d.domain_id, label: d.domain_name ?? d.domain_id })),
    [domains],
  )
  const profileOptions = useMemo(
    () => profiles.map((p) => ({ value: p.profile_id, label: `${p.name}（${p.education}）` })),
    [profiles],
  )

  const run = async () => {
    if (!profileId) return
    setLoading(true)
    setError(null)
    try {
      setResult(await runPipeline({ profile_id: profileId, query, domain_id: domainId, llm: llmConfig }))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  // Highlight nodes related to the selected claim
  const highlightIds = useMemo(() => {
    if (!selectedClaimId || !result || !graph) return new Set<string>()
    const claim = result.claims.find((c) => c.claim_id === selectedClaimId)
    if (!claim) return new Set<string>()
    const ids = new Set<string>()
    for (const node of graph.nodes) {
      if (node.label === claim.source || node.label === claim.target) ids.add(node.id)
    }
    for (const eid of claim.evidence_ids) ids.add(eid)
    return ids
  }, [selectedClaimId, result, graph])

  const selectedClaim = result?.claims.find((c) => c.claim_id === selectedClaimId)
  const selectedEvidence = selectedClaim
    ? (result?.evidence_details?.[selectedClaim.claim_id] ?? [])
    : []

  const thinkingSteps = result
    ? [...result.specialist_agent_trace, ...result.agent_trace]
    : []

  return (
    <div className="research-page">
      <section className="page-lede">
        <div>
          <p className="section-index">01 / RESEARCH DESK</p>
          <h2>从论文证据，抵达可复核的科研判断。</h2>
          <p className="page-lede__summary">
            系统先寻找原文证据，再让提出者、批判者与裁判处理争议。任何入图关系都必须能回到章节与字符跨度。
          </p>
        </div>
        <dl className="method-facts">
          <div>
            <dt>证据约束</dt>
            <dd>强制溯源</dd>
          </div>
          <div>
            <dt>核心决策</dt>
            <dd>3 Agents</dd>
          </div>
          <div>
            <dt>真实金标准</dt>
            <dd className="is-pending">待核验</dd>
          </div>
        </dl>
      </section>

      <Card className="query-card" variant="outlined">
        <div className="query-card__header">
          <div>
            <span className="editorial-kicker">RESEARCH QUESTION</span>
            <h3>提出一个需要跨论文证据的问题</h3>
          </div>
          <p>输出会区分已接受、待复核与已拒绝的主张。</p>
        </div>
        <div className="query-grid">
          <label className="field-block">
            <span>垂直领域</span>
            <Select
              style={{ width: '100%' }}
              options={domainOptions}
              value={domainId}
              onChange={(value: string) => setDomainId(value)}
            />
          </label>
          <label className="field-block">
            <span>学习者画像</span>
            <Select
              style={{ width: '100%' }}
              options={profileOptions}
              value={profileId}
              onChange={(value: string) => setProfileId(value)}
            />
          </label>
          <div className="field-block">
            <LlmModelSelector value={llmConfig} onChange={setLlmConfig} />
          </div>
          <label className="field-block field-block--query">
            <span>研究问题</span>
            <Input.TextArea
              rows={2}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="例如：分析图神经网络如何支持稳定材料发现"
            />
          </label>
          <div className="query-action">
            <Button type="primary" onClick={run} loading={loading} block size="large">
              开始证据推理
            </Button>
            <small>运行后生成可追溯 run_id</small>
          </div>
        </div>
      </Card>

      {error && <Alert style={{ marginTop: 16 }} type="error" message={error} showIcon />}

      {loading && (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Space direction="vertical" size="middle">
            <Spin size="large" />
            <Text type="secondary">多智能体协同决策运行中…</Text>
          </Space>
        </div>
      )}

      {result && !loading && (
        <>
          <Alert
            className="metric-disclosure"
            type="warning"
            showIcon
            message="指标披露"
            description="当前页面中的适配率与覆盖率属于开发阶段代理指标；L3 人工金标准完成前，不作为对外实测结论。"
          />
          <Card
            title={`思考过程 · ${thinkingSteps.length} 个 Agent`}
            style={{ marginTop: 16 }}
            extra={result.run_id ? <Tag>run_id: {result.run_id.slice(0, 12)}</Tag> : null}
          >
            <AgentTrace steps={thinkingSteps} />
          </Card>

          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={6}>
              <Card><Statistic title="accepted 命题" value={result.metrics.accepted_claims} /></Card>
            </Col>
            <Col span={6}>
              <Card><Statistic title="rejected 命题" value={result.metrics.rejected_claims} /></Card>
            </Col>
            <Col span={6}>
              <Card><Statistic title="难度适配准确率" value={result.metrics.adaptation_accuracy} suffix="%" /></Card>
            </Col>
            <Col span={6}>
              <Card><Statistic title="知识覆盖率" value={result.metrics.knowledge_coverage_rate} suffix="%" /></Card>
            </Col>
          </Row>

          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={8}>
              <Card title="学习者知识画像">
                <DiagnosisRadar profile={result.profile} />
              </Card>
            </Col>
            <Col span={16}>
              <Card title="裁决命题（点击命题联动图谱与证据原文）" extra={<Text type="secondary" style={{ fontSize: 11 }}>共 {result.claims.length} 条</Text>}>
                <div style={{ maxHeight: 320, overflowY: 'auto' }}>
                  {result.claims.map((claim) => (
                    <div
                      key={claim.claim_id}
                      onClick={() => setSelectedClaimId(selectedClaimId === claim.claim_id ? null : claim.claim_id)}
                      style={{
                        padding: '8px 10px',
                        marginBottom: 4,
                        border: selectedClaimId === claim.claim_id ? '1px solid #a51931' : '1px solid #f0ece4',
                        borderLeft: selectedClaimId === claim.claim_id ? '3px solid #a51931' : '3px solid transparent',
                        borderRadius: 2,
                        cursor: 'pointer',
                        background: selectedClaimId === claim.claim_id ? '#fdf0f2' : '#fff',
                        fontSize: 12,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                        {statusTag(claim.status)}
                        <Text strong style={{ fontSize: 12 }}>{claim.source}</Text>
                        <Text type="secondary" style={{ fontSize: 11 }}>-{claim.relation}-&gt;</Text>
                        <Text strong style={{ fontSize: 12 }}>{claim.target}</Text>
                        <Text type="secondary" style={{ marginLeft: 'auto', fontSize: 11 }}>{(claim.judge_score * 100).toFixed(0)}%</Text>
                      </div>
                      {claim.criticisms.length > 0 && (
                        <Text type="secondary" style={{ fontSize: 10 }}>批判: {claim.criticisms.join('；')}</Text>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            </Col>
          </Row>

          <Card
            title="证据知识图谱（命题→证据跨度→实体→关系，点击命题高亮联动）"
            style={{ marginTop: 16 }}
          >
            {graph ? (
              <Row gutter={12}>
                <Col span={15}>
                  <KnowledgeGraphView data={graph} highlightIds={highlightIds} height={480} />
                </Col>
                <Col span={9}>
                  <div style={{ height: 480, overflowY: 'auto', border: '1px solid #f0ece4', borderRadius: 4, padding: 10 }}>
                    {selectedClaim ? (
                      <>
                        <div style={{ marginBottom: 10, paddingBottom: 8, borderBottom: '1px solid #f0ece4' }}>
                          <Text strong style={{ fontSize: 12 }}>{selectedClaim.source} → {selectedClaim.target}</Text>
                          <br />
                          <Text type="secondary" style={{ fontSize: 10 }}>
                            {selectedClaim.relation_type} · {statusTag(selectedClaim.status)} · {(selectedClaim.judge_score * 100).toFixed(0)}% · {selectedEvidence.length} 条证据
                          </Text>
                        </div>
                        {selectedEvidence.length > 0 ? selectedEvidence.map((span) => (
                          <div key={span.evidence_id} style={{ marginBottom: 10, padding: 8, background: '#faf8f4', borderLeft: '3px solid #a51931', fontSize: 11, lineHeight: 1.6 }}>
                            <Text type="secondary" style={{ fontSize: 9, display: 'block', marginBottom: 3 }}>
                              {span.section_id} · 字符 [{span.char_start}, {span.char_end})
                            </Text>
                            <div style={{ color: '#334155' }}>{span.text}</div>
                          </div>
                        )) : (
                          <Text type="secondary" style={{ fontSize: 11 }}>该命题无关联证据跨度。</Text>
                        )}
                      </>
                    ) : (
                      <div style={{ textAlign: 'center', paddingTop: 160, color: '#9a938a', fontSize: 12 }}>
                        点击左侧命题查看<br />证据原文与图谱联动
                      </div>
                    )}
                  </div>
                </Col>
              </Row>
            ) : (
              <Paragraph type="secondary">图谱加载中或不可用。</Paragraph>
            )}
          </Card>

          <Card title="个性化资源" style={{ marginTop: 16 }}>
            <Collapse
              items={[
                {
                  key: 'briefing',
                  label: '导读',
                  children: (
                    <Paragraph>
                      <Text strong>{result.resources.briefing.title}</Text>
                      <br />
                      {result.resources.briefing.strategy}
                    </Paragraph>
                  ),
                },
                {
                  key: 'guide',
                  label: '实操指南',
                  children: <pre>{JSON.stringify(result.resources.practical_guide, null, 2)}</pre>,
                },
                {
                  key: 'quiz',
                  label: '分阶测评',
                  children: <pre>{JSON.stringify(result.resources.quiz, null, 2)}</pre>,
                },
                {
                  key: 'blue',
                  label: '蓝海 Idea（待验证假设）',
                  children: <Paragraph>{result.resources.blue_ocean.hypothesis}</Paragraph>,
                },
              ]}
            />
          </Card>
        </>
      )}
    </div>
  )
}
