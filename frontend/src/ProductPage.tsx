import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Input,
  List,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
} from 'antd'
import {
  BookOutlined,
  CloudDownloadOutlined,
  LinkOutlined,
  PlayCircleOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from '@ant-design/icons'
import AgentTrace from './AgentTrace'
import DiagnosisRadar from './DiagnosisRadar'
import KnowledgeGraphView from './KnowledgeGraphView'
import ResourceSummary from './ResourceSummary'
import ResearchProgress from './ResearchProgress'
import { getDomains, getExtractedGraph, getProfiles, getProviders, searchOnline, sendFeedback, streamPipeline, testProvider } from './api'
import type {
  Domain,
  GraphData,
  LearnerProfile,
  ProviderOption,
  RunResult,
  ResearchProgressEvent,
} from './types'

const { Text, Paragraph } = Typography

const requestedProvider = new URLSearchParams(window.location.search).get('provider')
function statusTag(status: string) {
  if (status === 'accepted') return <Tag color="green">accepted</Tag>
  if (status === 'rejected') return <Tag color="red">rejected</Tag>
  return <Tag color="orange">needs_review</Tag>
}

export default function ProductPage() {
  const [domains, setDomains] = useState<Domain[]>([])
  const [profiles, setProfiles] = useState<LearnerProfile[]>([])
  const [providers, setProviders] = useState<ProviderOption[]>([])
  const [domainId, setDomainId] = useState<string | undefined>()
  const [profileId, setProfileId] = useState<string | undefined>()
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<RunResult | null>(null)
  const [progressEvents, setProgressEvents] = useState<ResearchProgressEvent[]>([])
  const [operationId, setOperationId] = useState('')
  const [progressStartedAt, setProgressStartedAt] = useState<number | null>(null)
  const [lastSignalAt, setLastSignalAt] = useState<number | null>(null)
  const [progressMode, setProgressMode] = useState<'offline' | 'online'>('offline')
  const [providerId, setProviderId] = useState('mock')
  const [model, setModel] = useState('offline-rules')
  const [apiKey, setApiKey] = useState('')
  const [onlineResult, setOnlineResult] = useState<Record<string, unknown> | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([getDomains(), getProfiles(), getProviders()])
      .then(([domainsData, profilesData, providerData]) => {
        if (cancelled) return
        setDomains(domainsData)
        setProfiles(profilesData)
        setProviders(providerData.providers)
        const startupProvider = providerData.providers.find(
          (item) => item.id === requestedProvider && item.available,
        )
        if (startupProvider) {
          setProviderId(startupProvider.id)
          setModel(startupProvider.default_model)
        }
        setDomainId(domainsData[0]?.domain_id)
        setProfileId(profilesData[0]?.profile_id ?? 'my-profile')
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
    () => profiles.map((p) => ({ value: p.profile_id, label: `${p.profile_kind === 'personal' ? '我的画像' : '演示'}｜${p.name}（${p.education}）` })),
    [profiles],
  )
  const selectedProvider = providers.find((item) => item.id === providerId)
  const selectedDomain = domains.find((item) => item.domain_id === domainId)
  const selectedProfile = profiles.find((item) => item.profile_id === profileId)
  const providerOptions = providers.map((item) => ({ value: item.id, disabled: !item.available, label: `${item.access_mode === 'offline' ? '离线' : item.access_mode === 'free' ? '免费' : 'BYOK'}｜${item.label}${item.available ? '' : '（不可用）'}` }))

  const run = async () => {
    if (!profileId) return
    setLoading(true)
    setError(null)
    setResult(null)
    setSelectedClaimId(null)
    setProgressEvents([])
    setOperationId('')
    const startedAt = Date.now()
    setProgressStartedAt(startedAt)
    setLastSignalAt(startedAt)
    setProgressMode(providerId === 'mock' ? 'offline' : 'online')
    try {
      setResult(await streamPipeline(
        { profile_id: profileId, query, domain_id: domainId, llm: { provider: providerId, model, api_key: apiKey } },
        {
          onStarted: (id) => { setOperationId(id); setLastSignalAt(Date.now()) },
          onProgress: (progress) => {
            setProgressEvents((items) => items.some((item) => item.sequence === progress.sequence) ? items : [...items, progress])
            setLastSignalAt(Date.now())
          },
          onHeartbeat: () => setLastSignalAt(Date.now()),
        },
      ))
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
  const onlinePapers = onlineResult && Array.isArray(onlineResult.results)
    ? onlineResult.results.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    : []

  return (
    <div className="research-page">
      <section className="page-lede page-lede--simple">
        <div><h2>从证据到判断</h2><p className="page-lede__summary">检索、质疑、裁决，每条结论均可回溯。</p></div>
      </section>

      <Card className="query-card" variant="outlined">
        <div className="query-card__header">
          <div>
            <span className="query-card__eyebrow">NEW RESEARCH RUN</span>
            <h3>把问题交给证据链</h3>
            <p>先定义问题，再配置证据范围与推理角色。</p>
          </div>
          <div className="query-flow" aria-label="运行步骤">
            <span><b>01</b> 检索</span>
            <span><b>02</b> 质疑</span>
            <span><b>03</b> 裁决</span>
          </div>
        </div>

        <div className="query-question">
          <label className="query-question__label" htmlFor="research-question">
            <span>01</span>
            <div><strong>研究问题</strong><small>描述希望验证的关系、机制或工程判断</small></div>
          </label>
          <Input.TextArea
            id="research-question"
            autoSize={{ minRows: 3, maxRows: 7 }}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="例如：分析图神经网络如何支持稳定材料发现"
          />
          <div className="query-question__footer">
            <span>{query.trim().length} 字</span>
            <span>结论将绑定论文来源与证据 ID</span>
          </div>
        </div>

        <div className="query-settings-heading">
          <div><span>02</span><strong>运行配置</strong></div>
          <small>这些选项决定检索边界、解释难度和模型调用方式</small>
        </div>
        <div className="query-grid query-settings">
          <label className="field-block">
            <span><BookOutlined /> 垂直领域</span>
            <Select
              style={{ width: '100%' }}
              options={domainOptions}
              value={domainId}
              onChange={(value: string) => setDomainId(value)}
            />
          </label>
          <label className="field-block">
            <span><UserOutlined /> 学习者画像</span>
            <Select
              style={{ width: '100%' }}
              options={profileOptions}
              value={profileId}
              onChange={(value: string) => setProfileId(value)}
            />
          </label>
          <label className="field-block provider-field">
            <span><RobotOutlined /> 推理服务</span>
            <Select
              style={{ width: '100%' }} options={providerOptions} value={providerId}
              onChange={(value: string) => { const next = providers.find((item) => item.id === value); setProviderId(value); setModel(next?.default_model ?? '') ; setApiKey('') }}
            />
          </label>
          <label className="field-block">
            <span><SafetyCertificateOutlined /> 模型</span>
            <Select style={{ width: '100%' }} options={(selectedProvider?.models ?? []).map((value) => ({ value, label: value }))} value={model} onChange={setModel} />
          </label>
          {selectedProvider?.access_mode === 'byok' && (
            <label className="field-block query-settings__key">
              <span>本次运行 API Key（不保存）</span>
              <Input.Password value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="仅随本次请求发送，不写入数据库或日志" />
            </label>
          )}
        </div>

        <div className="query-action">
          <div className="query-action__context">
            <span className="query-action__dot" />
            <div>
              <strong>{selectedProvider?.label ?? '正在读取模型'}</strong>
              <small>{selectedDomain?.domain_name ?? '未选择领域'} · {selectedProfile?.name ?? '未选择画像'}</small>
            </div>
          </div>
          <div className="query-action__buttons">
            {selectedProvider && <Button icon={<LinkOutlined />} disabled={loading || selectedProvider.access_mode === 'offline' || (selectedProvider.requires_api_key && !apiKey)} onClick={() => testProvider({ provider: providerId, model, api_key: apiKey }).then(() => setError(null)).catch((err: Error) => setError(err.message))}>测试连接</Button>}
            <Button type="primary" onClick={run} loading={loading} disabled={query.trim().length < 2} size="large">
              <PlayCircleOutlined />开始循证研究
            </Button>
          </div>
        </div>
      </Card>

      {error && <Alert style={{ marginTop: 16 }} type="error" message={error} showIcon />}

      {progressStartedAt !== null && (loading || progressEvents.length > 0) && (
        <ResearchProgress
          events={progressEvents}
          running={loading}
          mode={progressMode}
          operationId={operationId}
          startedAt={progressStartedAt}
          lastSignalAt={lastSignalAt}
          result={result}
          error={error}
        />
      )}

      {result && !loading && (
        <>
          <div className="run-meta">
            <Tag>{result.provider_run?.provider_label ?? result.provider_run?.provider ?? '离线规则'} · {result.provider_run?.model ?? ''}</Tag>
            {result.persistence?.saved && <Tag color="green">已保存</Tag>}
            <Tag icon={<SafetyCertificateOutlined />}>Key 不留存</Tag>
          </div>
          <Card
            title={`智能体轨迹 · ${thinkingSteps.length}`}
            style={{ marginTop: 16 }}
            extra={result.run_id ? <Tag>run_id: {result.run_id.slice(0, 12)}</Tag> : null}
          >
            <AgentTrace steps={thinkingSteps} />
          </Card>

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} md={8}>
              <Card><Statistic title="已接受" value={result.claims.filter((claim) => claim.status === 'accepted').length} /></Card>
            </Col>
            <Col xs={24} md={8}>
              <Card><Statistic title="待复核" value={result.claims.filter((claim) => ['review', 'needs_review'].includes(claim.status)).length} /></Card>
            </Col>
            <Col xs={24} md={8}>
              <Card><Statistic title="已拒绝" value={result.claims.filter((claim) => claim.status === 'rejected').length} /></Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={10}>
              <Card title="学习者知识画像">
                <DiagnosisRadar profile={result.profile} />
              </Card>
            </Col>
            <Col xs={24} lg={14}>
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
              <Row gutter={[12, 12]}>
                <Col xs={24} lg={15}>
                  <KnowledgeGraphView data={graph} highlightIds={highlightIds} height={480} />
                </Col>
                <Col xs={24} lg={9}>
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
            <ResourceSummary resources={result.resources} />
          </Card>
          <Card title="调整难度" style={{ marginTop: 16 }}>
            <Space wrap>
              {([
                ['too_hard', '太难，降维解释'], ['suitable', '难度合适'], ['too_easy', '太简单，进阶挑战'],
              ] as const).map(([feedback, label]) => (
                <Button key={feedback} onClick={async () => {
                  if (!profileId) return
                  setProgressStartedAt(null)
                  setProgressEvents([])
                  setLoading(true)
                  try { setResult(await sendFeedback({ profile_id: profileId, query, domain_id: domainId, feedback })) }
                  catch (err) { setError(err instanceof Error ? err.message : String(err)) }
                  finally { setLoading(false) }
                }}>{label}</Button>
              ))}
            </Space>
            {result.feedback?.decision && <Paragraph style={{ marginTop: 12 }}>{result.feedback.decision}</Paragraph>}
          </Card>
          <Card title="候选文献" extra={<Tag color="orange">待复核</Tag>} style={{ marginTop: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button icon={<CloudDownloadOutlined />} onClick={async () => {
                try { setOnlineResult(await searchOnline({ query, limit: 5, allow_network: true })) }
                catch (err) { setError(err instanceof Error ? err.message : String(err)) }
              }}>检索候选</Button>
              {onlineResult && (
                <List
                  size="small"
                  locale={{ emptyText: '没有找到候选文献' }}
                  dataSource={onlinePapers}
                  renderItem={(paper) => (
                    <List.Item>
                      <List.Item.Meta
                        title={paper.source_url ? <Typography.Link href={String(paper.source_url)} target="_blank">{String(paper.title ?? '未命名文献')}</Typography.Link> : String(paper.title ?? '未命名文献')}
                        description={[paper.year, paper.venue].filter(Boolean).join(' · ')}
                      />
                    </List.Item>
                  )}
                />
              )}
            </Space>
          </Card>
        </>
      )}
    </div>
  )
}
