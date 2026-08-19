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
import { getDomains, getHealth, getProfiles, runPipeline } from './api'
import type { Claim, Domain, Health, LearnerProfile, RunResult } from './types'

const { Title, Paragraph, Text } = Typography

interface ClaimRow {
  key: string
  claim: string
  status: string
  score: number
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
]

export default function App() {
  const [domains, setDomains] = useState<Domain[]>([])
  const [profiles, setProfiles] = useState<LearnerProfile[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [domainId, setDomainId] = useState<string | undefined>()
  const [profileId, setProfileId] = useState<string | undefined>()
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<RunResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([getDomains(), getProfiles(), getHealth()])
      .then(([domainsData, profilesData, healthData]) => {
        if (cancelled) return
        setDomains(domainsData)
        setProfiles(profilesData)
        setHealth(healthData)
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

  const domainOptions = useMemo(
    () =>
      domains.map((d) => ({
        value: d.domain_id,
        label: d.domain_name ?? d.domain_id,
      })),
    [domains],
  )
  const profileOptions = useMemo(
    () =>
      profiles.map((p) => ({
        value: p.profile_id,
        label: `${p.name}（${p.education}）`,
      })),
    [profiles],
  )

  const run = async () => {
    if (!profileId) return
    setLoading(true)
    setError(null)
    try {
      const data = await runPipeline({
        profile_id: profileId,
        query,
        domain_id: domainId,
      })
      setResult(data)
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
  }))

  return (
    <div style={{ maxWidth: 1120, margin: '0 auto', padding: 24 }}>
      <Title level={3}>研海寻踪 · 多智能体协同决策</Title>
      <Paragraph type="secondary">
        {health
          ? `后端在线 · ${health.domain_count} 领域 · ${health.profile_count} 画像 · ${health.system_agents} Agent`
          : '正在连接后端…'}
      </Paragraph>

      <Card>
        <Row gutter={16} align="bottom">
          <Col span={5}>
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
          <Col span={11}>
            <Text>查询 / 学习目标</Text>
            <Input value={query} onChange={(e) => setQuery(e.target.value)} />
          </Col>
          <Col span={3}>
            <Button type="primary" onClick={run} loading={loading} block>
              运行
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
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={6}>
              <Card>
                <Statistic title="accepted 命题" value={result.metrics.accepted_claims} />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic title="rejected 命题" value={result.metrics.rejected_claims} />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="难度适配准确率"
                  value={result.metrics.adaptation_accuracy}
                  suffix="%"
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="知识覆盖率"
                  value={result.metrics.knowledge_coverage_rate}
                  suffix="%"
                />
              </Card>
            </Col>
          </Row>

          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={10}>
              <Card title="学习者知识画像">
                <DiagnosisRadar profile={result.profile} />
              </Card>
            </Col>
            <Col span={14}>
              <Card title="多智能体调度轨迹">
                <AgentTrace
                  steps={[...result.specialist_agent_trace, ...result.agent_trace]}
                />
              </Card>
            </Col>
          </Row>

          <Card title="裁决命题" style={{ marginTop: 16 }}>
            <Table
              columns={claimColumns}
              dataSource={claimRows}
              pagination={false}
              size="small"
            />
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
                  children: (
                    <pre>{JSON.stringify(result.resources.practical_guide, null, 2)}</pre>
                  ),
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
