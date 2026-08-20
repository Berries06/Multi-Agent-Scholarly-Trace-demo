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
import { getDomains, getExtractedGraph, getProfiles, runPipeline } from './api'
import type {
  Claim,
  Domain,
  GraphData,
  LearnerProfile,
  RunResult,
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
  const [domainId, setDomainId] = useState<string | undefined>()
  const [profileId, setProfileId] = useState<string | undefined>()
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<RunResult | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)
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
      setResult(await runPipeline({ profile_id: profileId, query, domain_id: domainId }))
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
    <div>
      <Card title="问一个领域问题">
        <Row gutter={12} align="bottom">
          <Col span={4}>
            <Text>垂直领域</Text>
            <Select
              style={{ width: '100%' }}
              options={domainOptions}
              value={domainId}
              onChange={(value: string) => setDomainId(value)}
            />
          </Col>
          <Col span={5}>
            <Text>学习者画像</Text>
            <Select
              style={{ width: '100%' }}
              options={profileOptions}
              value={profileId}
              onChange={(value: string) => setProfileId(value)}
            />
          </Col>
          <Col span={12}>
            <Text>你的问题</Text>
            <Input.TextArea
              rows={2}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="例如：分析图神经网络如何支持稳定材料发现"
            />
          </Col>
          <Col span={3}>
            <Button type="primary" onClick={run} loading={loading} block>
              提交
            </Button>
          </Col>
        </Row>
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
        </>
      )}
    </div>
  )
}
