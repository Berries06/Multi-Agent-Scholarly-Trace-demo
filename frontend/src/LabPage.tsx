import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Input,
  Row,
  Select,
  Slider,
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
import { getProfiles, ingestPaper } from './api'
import type {
  DecisionClaim,
  ExtractedEntity,
  ExtractedRelation,
  IngestResult,
  LearnerProfile,
} from './types'

const { Text, Paragraph } = Typography
const { TextArea } = Input

const EXAMPLE_PAPER = `# 面向科研文献的多智能体证据裁决系统

## 摘要
我们提出一种多智能体辩论机制，用于减少检索增强生成中的幻觉。
系统在 SciERC 数据集上评测，实体抽取 F1 提升到 84.6%，并支持
对知识图谱进行证据约束检索。

## 方法
我们采用角色扮演协作与反思机制构建三个智能体：提出者、批判者、裁判。
提出者基于 GLiNER 抽取实体，GLiREL 生成关系候选，批判者对证据跨度进行
交叉验证，裁判对候选关系进行置信裁决。

## 实验
在 SciERC 与 SciREX 上评测。结果显示多智能体辩论显著改善了事实性，
知识覆盖率提升 12%，但仍存在不确定性，尤其是分布外评测场景。
`

function statusTag(status: string) {
  if (status === 'accepted') return <Tag color="green">accepted</Tag>
  if (status === 'rejected') return <Tag color="red">rejected</Tag>
  return <Tag color="orange">needs_review</Tag>
}

interface ClaimRow {
  key: string
  claim: string
  relation_type: string
  status: string
  score: number
}

const claimColumns: ColumnsType<ClaimRow> = [
  { title: '命题', dataIndex: 'claim', key: 'claim' },
  { title: '关系类型', dataIndex: 'relation_type', key: 'relation_type' },
  { title: '状态', dataIndex: 'status', key: 'status', render: statusTag },
  { title: '裁判分', dataIndex: 'score', key: 'score' },
]

function toClaimRows(claims: DecisionClaim[]): ClaimRow[] {
  return claims.map((c) => ({
    key: c.claim_id,
    claim: `${c.source} -${c.relation}-> ${c.target}`,
    relation_type: c.relation_type,
    status: c.status,
    score: c.judge_score,
  }))
}

export default function LabPage() {
  const [profiles, setProfiles] = useState<LearnerProfile[]>([])
  const [profileId, setProfileId] = useState<string | undefined>()
  const [paperId, setPaperId] = useState('member-paper-01')
  const [title, setTitle] = useState('')
  const [text, setText] = useState(EXAMPLE_PAPER)
  const [threshold, setThreshold] = useState(0.72)
  const [result, setResult] = useState<IngestResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getProfiles()
      .then((data) => {
        setProfiles(data)
        setProfileId(data[0]?.profile_id)
      })
      .catch((err: Error) => setError(err.message))
  }, [])

  const profileOptions = useMemo(
    () => profiles.map((p) => ({ value: p.profile_id, label: `${p.name}（${p.education}）` })),
    [profiles],
  )
  const selectedProfile = useMemo(
    () => profiles.find((p) => p.profile_id === profileId),
    [profiles, profileId],
  )

  const run = async () => {
    if (!profileId) return
    setLoading(true)
    setError(null)
    try {
      const data = await ingestPaper({
        paper_id: paperId,
        title,
        text,
        profile_id: profileId,
        accept_threshold: threshold,
      })
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const entityById = useMemo(() => {
    const map: Record<string, ExtractedEntity> = {}
    for (const e of result?.extraction.entities ?? []) map[e.entity_id] = e
    return map
  }, [result])

  const relationRows = (result?.extraction.relations ?? []).map((r: ExtractedRelation) => ({
    key: r.relation_id,
    link: `${entityById[r.source_id]?.canonical_name ?? r.source_id} → ${entityById[r.target_id]?.canonical_name ?? r.target_id}`,
    type: r.relation_type,
    status: r.status,
    confidence: r.confidence,
    evidence: r.evidence_ids.join(' | '),
  }))

  const entityRows = (result?.extraction.entities ?? []).map((e: ExtractedEntity) => ({
    key: e.entity_id,
    name: e.canonical_name,
    type: e.entity_type,
    mentions: e.mentions.length,
    confidence: e.confidence,
  }))

  const thinkingSteps = result
    ? [
        {
          agent: '论文知识抽取',
          role: '结构解析 + 实体/关系抽取',
          status: 'completed',
          summary: `抽取 ${result.summary.entity_count} 个实体、${result.summary.candidate_relation_count} 条关系候选`,
        },
        {
          agent: '学情诊断',
          role: '画像 → 难度/盲区',
          status: 'completed',
          summary: `准备度 ${result.diagnosis.readiness_score}，目标难度 L${result.diagnosis.target_difficulty}`,
        },
        {
          agent: '提出者',
          role: '候选命题',
          status: 'completed',
          summary: `生成 ${result.proposed_claims.length} 条候选命题`,
        },
        {
          agent: '批判者',
          role: '反证与约束',
          status: 'completed',
          summary: '对每条命题做证据存在性、类型约束、跨度覆盖检查',
        },
        {
          agent: '裁判',
          role: '置信裁决',
          status: 'completed',
          summary: `accepted ${result.summary.accepted_count} / rejected ${result.summary.rejected_count}`,
        },
      ]
    : []

  return (
    <div>
      <Paragraph type="secondary">
        粘贴一篇论文正文，平台从「结构解析 → 实体/关系抽取 → 学情诊断 → 三智能体裁决 → 个性化资源」
        逐层展示中间量。这是团队亲手验收 AI 抽取与裁决质量的地方。
      </Paragraph>

      <Card>
        <Row gutter={16} align="bottom">
          <Col span={4}>
            <Text>论文 ID</Text>
            <Input value={paperId} onChange={(e) => setPaperId(e.target.value)} />
          </Col>
          <Col span={4}>
            <Text>论文标题（可选）</Text>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="留空取第一个标题" />
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
          <Col span={8}>
            <Text>accept_threshold（裁决接收阈值）</Text>
            <Slider
              min={0.5}
              max={0.95}
              step={0.01}
              value={threshold}
              onChange={setThreshold}
            />
          </Col>
          <Col span={3}>
            <Button type="primary" onClick={run} loading={loading} block>
              运行流水线
            </Button>
          </Col>
        </Row>
        <TextArea
          style={{ marginTop: 16 }}
          rows={10}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="粘贴论文正文（Markdown，# 标题分段）"
        />
      </Card>

      {error && <Alert style={{ marginTop: 16 }} type="error" message={error} showIcon />}

      {loading && (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Space direction="vertical" size="middle">
            <Spin size="large" />
            <Text type="secondary">论文解析与多智能体裁决运行中…</Text>
          </Space>
        </div>
      )}

      {result && !loading && (
        <>
          <Card title={`思考过程 · ${thinkingSteps.length} 个 Agent`} style={{ marginTop: 16 }}>
            <AgentTrace steps={thinkingSteps} />
          </Card>

          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={6}>
              <Card><Statistic title="实体数" value={result.summary.entity_count} /></Card>
            </Col>
            <Col span={6}>
              <Card><Statistic title="关系候选" value={result.summary.candidate_relation_count} /></Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="accepted / rejected"
                  value={result.summary.accepted_count}
                  suffix={`/ ${result.summary.rejected_count}`}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="护栏：无证据 accepted"
                  value={result.summary.accepted_without_evidence_count}
                  valueStyle={{ color: result.summary.accepted_without_evidence_count === 0 ? '#3f8600' : '#cf1322' }}
                />
              </Card>
            </Col>
          </Row>

          <Card title="运行指纹" style={{ marginTop: 16 }}>
            <Descriptions size="small" column={3}>
              <Descriptions.Item label="论文 ID">{result.fingerprint.paper_id}</Descriptions.Item>
              <Descriptions.Item label="标题">{result.fingerprint.title}</Descriptions.Item>
              <Descriptions.Item label="字符数">{result.fingerprint.text_char_count}</Descriptions.Item>
              <Descriptions.Item label="画像">{result.fingerprint.profile_id}</Descriptions.Item>
              <Descriptions.Item label="接收阈值">{result.fingerprint.accept_threshold}</Descriptions.Item>
              <Descriptions.Item label="schema 版本">{result.fingerprint.schema_version}</Descriptions.Item>
            </Descriptions>
          </Card>

          <Card title="1. 结构解析（章节与原文）" style={{ marginTop: 16 }}>
            {Object.entries(result.document.sections).map(([name, content]) => (
              <div key={name} style={{ marginBottom: 12 }}>
                <Text strong>{name}</Text>（{content.length} 字符）
                <pre style={{ whiteSpace: 'pre-wrap', background: '#fafafa', padding: 12, borderRadius: 6 }}>{content}</pre>
              </div>
            ))}
          </Card>

          <Card title="2. 实体 / 关系抽取" style={{ marginTop: 16 }}>
            <Text strong>实体（{entityRows.length}）</Text>
            <Table
              size="small"
              style={{ marginTop: 8 }}
              columns={[
                { title: '规范名', dataIndex: 'name', key: 'name' },
                { title: '类型', dataIndex: 'type', key: 'type' },
                { title: '提及次数', dataIndex: 'mentions', key: 'mentions' },
                { title: '置信度', dataIndex: 'confidence', key: 'confidence' },
              ]}
              dataSource={entityRows}
              pagination={false}
            />
            <Text strong style={{ display: 'block', marginTop: 16 }}>关系候选（{relationRows.length}）</Text>
            <Table
              size="small"
              style={{ marginTop: 8 }}
              columns={[
                { title: '源 → 目标', dataIndex: 'link', key: 'link' },
                { title: '类型', dataIndex: 'type', key: 'type' },
                { title: '上游状态', dataIndex: 'status', key: 'status', render: statusTag },
                { title: '置信度', dataIndex: 'confidence', key: 'confidence' },
                { title: '证据 ID', dataIndex: 'evidence', key: 'evidence' },
              ]}
              dataSource={relationRows}
              pagination={false}
            />
          </Card>

          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={10}>
              <Card title="3. 学情诊断">
                {selectedProfile && <DiagnosisRadar profile={selectedProfile} />}
                <Descriptions size="small" column={1}>
                  <Descriptions.Item label="准备度">{result.diagnosis.readiness_score}</Descriptions.Item>
                  <Descriptions.Item label="目标难度">L{result.diagnosis.target_difficulty}</Descriptions.Item>
                  <Descriptions.Item label="盲区">{result.diagnosis.blind_spots.join('、') || '无'}</Descriptions.Item>
                  <Descriptions.Item label="强项">{result.diagnosis.strengths.join('、') || '无'}</Descriptions.Item>
                </Descriptions>
              </Card>
            </Col>
            <Col span={14}>
              <Card title="4. 三智能体裁决">
                <Collapse
                  items={[
                    {
                      key: 'propose',
                      label: `提出者 · ${result.proposed_claims.length} 条候选`,
                      children: (
                        <Table
                          size="small"
                          columns={claimColumns}
                          dataSource={toClaimRows(result.proposed_claims)}
                          pagination={false}
                        />
                      ),
                    },
                    {
                      key: 'critic',
                      label: '批判者 · 逐条批判项',
                      children: (
                        <div>
                          {result.critiqued_claims.map((c) => (
                            <div key={c.claim_id} style={{ marginBottom: 8 }}>
                              <Text strong>
                                {c.claim_id} · {c.source} -{c.relation}→ {c.target}
                              </Text>
                              <div>{c.criticisms.join('；')}</div>
                            </div>
                          ))}
                        </div>
                      ),
                    },
                    {
                      key: 'judge',
                      label: `裁判 · 最终裁决`,
                      children: (
                        <Table
                          size="small"
                          columns={[
                            ...claimColumns,
                            { title: '裁决理由', dataIndex: 'reason', key: 'reason' },
                          ]}
                          dataSource={toClaimRows(result.adjudicated_claims).map((row, i) => ({
                            ...row,
                            reason: result.adjudicated_claims[i]?.judge_reason ?? '',
                          }))}
                          pagination={false}
                        />
                      ),
                    },
                  ]}
                />
              </Card>
            </Col>
          </Row>

          <Card title="5. 个性化资源" style={{ marginTop: 16 }}>
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
