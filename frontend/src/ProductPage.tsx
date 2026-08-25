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
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import AgentTrace from './AgentTrace'
import DiagnosisRadar from './DiagnosisRadar'
import KnowledgeGraphView from './KnowledgeGraphView'
import { getDomains, getExtractedGraph, getProfiles, getProviders, searchOnline, sendFeedback, streamPipeline, testProvider } from './api'
import type {
  Claim,
  Domain,
  GraphData,
  LearnerProfile,
  ProviderOption,
  RunResult,
  AgentTraceStep,
} from './types'

const { Text, Paragraph } = Typography

interface ClaimRow {
  key: string
  claim: string
  status: string
  score: number
  criticisms: string
}

function statusTag(status: string) {
  if (status === 'accepted') return <Tag color="green">accepted</Tag>
  if (status === 'rejected') return <Tag color="red">rejected</Tag>
  return <Tag color="orange">needs_review</Tag>
}

const claimColumns: ColumnsType<ClaimRow> = [
  { title: '命题', dataIndex: 'claim', key: 'claim' },
  { title: '状态', dataIndex: 'status', key: 'status', render: statusTag },
  { title: '裁判分', dataIndex: 'score', key: 'score' },
  { title: '批判项', dataIndex: 'criticisms', key: 'criticisms' },
]

export default function ProductPage() {
  const [domains, setDomains] = useState<Domain[]>([])
  const [profiles, setProfiles] = useState<LearnerProfile[]>([])
  const [providers, setProviders] = useState<ProviderOption[]>([])
  const [domainId, setDomainId] = useState<string | undefined>()
  const [profileId, setProfileId] = useState<string | undefined>()
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<RunResult | null>(null)
  const [liveSteps, setLiveSteps] = useState<AgentTraceStep[]>([])
  const [operationId, setOperationId] = useState('')
  const [providerId, setProviderId] = useState('mock')
  const [model, setModel] = useState('offline-rules')
  const [apiKey, setApiKey] = useState('')
  const [onlineResult, setOnlineResult] = useState<Record<string, unknown> | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([getDomains(), getProfiles(), getProviders()])
      .then(([domainsData, profilesData, providerData]) => {
        if (cancelled) return
        setDomains(domainsData)
        setProfiles(profilesData)
        setProviders(providerData)
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
  const providerOptions = providers.map((item) => ({ value: item.id, disabled: !item.available, label: `${item.access_mode === 'offline' ? '离线' : item.access_mode === 'free' ? '免费' : 'BYOK'}｜${item.label}${item.available ? '' : '（不可用）'}` }))

  const run = async () => {
    if (!profileId) return
    setLoading(true)
    setError(null)
    setLiveSteps([])
    setOperationId('')
    try {
      setResult(await streamPipeline(
        { profile_id: profileId, query, domain_id: domainId, llm: { provider: providerId, model, api_key: apiKey } },
        { onStarted: setOperationId, onStep: (step) => setLiveSteps((items) => [...items, step]) },
      ))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const claimRows: ClaimRow[] = (result?.claims ?? []).map((claim: Claim) => ({
    key: claim.claim_id,
    claim: `${claim.source} -${claim.relation}-> ${claim.target}`,
    status: claim.status,
    score: claim.judge_score,
    criticisms: claim.criticisms.join('；') || '—',
  }))

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
            <span>推理模式</span>
            <Select
              style={{ width: '100%' }} options={providerOptions} value={providerId}
              onChange={(value: string) => { const next = providers.find((item) => item.id === value); setProviderId(value); setModel(next?.default_model ?? '') ; setApiKey('') }}
            />
          </label>
          <label className="field-block">
            <span>模型</span>
            <Select style={{ width: '100%' }} options={(selectedProvider?.models ?? []).map((value) => ({ value, label: value }))} value={model} onChange={setModel} />
          </label>
          {selectedProvider?.access_mode === 'byok' && (
            <label className="field-block field-block--query">
              <span>本次运行 API Key（不保存）</span>
              <Input.Password value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="仅随本次请求发送，不写入数据库或日志" />
            </label>
          )}
          <label className="field-block">
            <span>学习者画像</span>
            <Select
              style={{ width: '100%' }}
              options={profileOptions}
              value={profileId}
              onChange={(value: string) => setProfileId(value)}
            />
          </label>
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
            {selectedProvider && <Button type="link" disabled={selectedProvider.access_mode === 'offline' || (selectedProvider.requires_api_key && !apiKey)} onClick={() => testProvider({ provider: providerId, model, api_key: apiKey }).then(() => setError(null)).catch((err: Error) => setError(err.message))}>测试模型连接</Button>}
          </div>
        </div>
      </Card>

      {error && <Alert style={{ marginTop: 16 }} type="error" message={error} showIcon />}

      {loading && (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Space direction="vertical" size="middle">
            <Spin size="large" />
            <Text type="secondary">多智能体协同决策运行中…</Text>
            {operationId && <Text code>{operationId}</Text>}
            {liveSteps.length > 0 && <AgentTrace steps={liveSteps} />}
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
          <Alert
            style={{ marginTop: 16 }} type="info" showIcon
            message={`${result.provider_run?.provider_label ?? result.provider_run?.provider ?? '离线规则'} · ${result.provider_run?.model ?? ''}`}
            description={`接入方式：${result.provider_run?.access_mode ?? result.provider_run?.mode ?? 'offline'}；运行已保存：${result.persistence?.saved ? '是' : '否'}；API Key 持久化：否。`}
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
            <Col span={10}>
              <Card title="学习者知识画像">
                <DiagnosisRadar profile={result.profile} />
              </Card>
            </Col>
            <Col span={14}>
              <Card title="裁决命题（点击行展开证据原文）">
                <Table
                  columns={claimColumns}
                  dataSource={claimRows}
                  pagination={false}
                  size="small"
                  expandable={{
                    expandedRowRender: (row) => {
                      const spans = result.evidence_details?.[row.key] ?? []
                      if (!spans.length) return <Text type="secondary">无证据跨度</Text>
                      return (
                        <div>
                          {spans.map((span) => (
                            <div key={span.evidence_id} style={{ marginBottom: 6 }}>
                              <Text strong>{span.evidence_id}</Text>
                              <Text type="secondary">
                                {' '}· {span.section_id} · 字符 [{span.char_start}, {span.char_end})
                              </Text>
                              <div style={{ color: '#334155' }}>{span.text}</div>
                            </div>
                          ))}
                        </div>
                      )
                    },
                  }}
                />
              </Card>
            </Col>
          </Row>

          <Card title="证据知识图谱（论文→证据跨度→实体→关系，点击节点看详情）" style={{ marginTop: 16 }}>
            {graph ? (
              <KnowledgeGraphView data={graph} />
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
          <Card title="训练反馈与下一轮调节" style={{ marginTop: 16 }}>
            <Space wrap>
              {([
                ['too_hard', '太难，降维解释'], ['suitable', '难度合适'], ['too_easy', '太简单，进阶挑战'],
              ] as const).map(([feedback, label]) => (
                <Button key={feedback} onClick={async () => {
                  if (!profileId) return
                  setLoading(true)
                  try { setResult(await sendFeedback({ profile_id: profileId, query, domain_id: domainId, feedback })) }
                  catch (err) { setError(err instanceof Error ? err.message : String(err)) }
                  finally { setLoading(false) }
                }}>{label}</Button>
              ))}
            </Space>
            {result.feedback?.decision && <Paragraph style={{ marginTop: 12 }}>{result.feedback.decision}</Paragraph>}
          </Card>
          <Card title="在线候选文献（只进入待复核区，不自动入图）" style={{ marginTop: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button onClick={async () => {
                try { setOnlineResult(await searchOnline({ query, limit: 5, allow_network: true })) }
                catch (err) { setError(err instanceof Error ? err.message : String(err)) }
              }}>检索 OpenAlex 候选</Button>
              {onlineResult && <pre>{JSON.stringify(onlineResult, null, 2)}</pre>}
            </Space>
          </Card>
        </>
      )}
    </div>
  )
}
