import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
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
  Upload,
} from 'antd'
import { InboxOutlined, PlayCircleOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import AgentTrace from './AgentTrace'
import DiagnosisRadar from './DiagnosisRadar'
import ResourceSummary from './ResourceSummary'
import { getProfiles, ingestPaper, ingestPdf } from './api'
import type {
  DecisionClaim,
  ExtractedEntity,
  ExtractedRelation,
  IngestResult,
  LearnerProfile,
} from './types'

const { Text } = Typography
const { TextArea } = Input

const EXAMPLE_PAPER = `# 面向科研文献的多智能体证据裁决系统

## 摘要
我们提出一种面向科研文献的证据裁决机制，为知识图谱中的每条关系
绑定可追溯的原文证据，并在证据变化时更新关系状态。

## 方法
系统由三个决策智能体协作：提出者生成候选关系，批判者检查证据存在性、
类型约束与跨度覆盖，裁判给出置信裁决。

## 实验
在自建文献语料上验证裁决协议的行为；结果与局限详见实验账本。
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
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const [saveSource, setSaveSource] = useState(false)
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
      let data: IngestResult
      if (pdfFile) {
        data = await ingestPdf({
          file: pdfFile,
          profile_id: profileId,
          paper_id: paperId,
          title,
          accept_threshold: threshold,
          save_source: saveSource,
        })
      } else {
        data = await ingestPaper({
          paper_id: paperId,
          title,
          text,
          profile_id: profileId,
          accept_threshold: threshold,
          save_source: saveSource,
        })
      }
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
    ? [...result.specialist_agent_trace, ...result.agent_trace]
    : []

  return (
    <div className="lab-page">
      <section className="page-lede page-lede--simple" aria-labelledby="intake-title">
        <div><h2 id="intake-title">论文摄入</h2><p className="page-lede__summary">抽取实体与关系，再由三个智能体复核。</p></div>
      </section>

      <Card className="intake-card" variant="outlined">
        <div className="intake-heading">
          <h3>论文与裁决设置</h3>
        </div>

        <div className="intake-grid">
          <label className="editorial-field">
            <span>论文 ID</span>
            <Input value={paperId} onChange={(e) => setPaperId(e.target.value)} />
          </label>
          <label className="editorial-field">
            <span>论文标题 <em>可选</em></span>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="留空取第一个标题" />
          </label>
          <label className="editorial-field">
            <span>学习者画像</span>
            <Select
              style={{ width: '100%' }}
              options={profileOptions}
              value={profileId}
              onChange={(value: string) => setProfileId(value)}
            />
          </label>
          <label className="editorial-field threshold-field">
            <span>裁决接收阈值 <strong>{threshold.toFixed(2)}</strong></span>
            <Slider
              min={0.5}
              max={0.95}
              step={0.01}
              value={threshold}
              onChange={setThreshold}
            />
          </label>
          <Button icon={<PlayCircleOutlined />} className="intake-run" type="primary" onClick={run} loading={loading} block>
            开始摄入
          </Button>
        </div>
        <div className="source-consent">
          <Checkbox checked={saveSource} onChange={(event) => setSaveSource(event.target.checked)}>保存论文原文</Checkbox>
          <Text type="secondary">默认不保存</Text>
        </div>

        <Upload.Dragger
          className="paper-dropzone"
          accept=".pdf"
          maxCount={1}
          beforeUpload={(file) => {
            setPdfFile(file)
            return false
          }}
          onRemove={() => setPdfFile(null)}
          fileList={pdfFile ? [{ uid: 'pdf-1', name: pdfFile.name }] : []}
        >
          <InboxOutlined className="dropzone-icon" />
          <p className="dropzone-title">拖入 PDF，或点击选择</p>
          <p className="dropzone-note">≤ 5MB · 需要文本层 · 扫描件请先 OCR</p>
        </Upload.Dragger>
        <label className="manuscript-field">
          <span>或粘贴结构化正文 <em>Markdown 标题将转换为章节</em></span>
          <TextArea
            rows={10}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="粘贴论文正文（Markdown，# 标题分段）"
          />
        </label>
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
          <Card title={`智能体轨迹 · ${thinkingSteps.length}`} style={{ marginTop: 16 }}>
            <AgentTrace steps={thinkingSteps} />
          </Card>

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={12} md={6}>
              <Card><Statistic title="实体数" value={result.summary.entity_count} /></Card>
            </Col>
            <Col xs={12} md={6}>
              <Card><Statistic title="关系候选" value={result.summary.candidate_relation_count} /></Card>
            </Col>
            <Col xs={12} md={6}>
              <Card><Statistic title="已接受" value={result.summary.accepted_count} /></Card>
            </Col>
            <Col xs={12} md={6}>
              <Card><Statistic title="待复核" value={result.summary.needs_review_count} /></Card>
            </Col>
          </Row>

          <Collapse
            className="technical-details"
            items={[{
              key: 'details',
              label: '运行与解析详情',
              children: <>
                <Descriptions size="small" column={3}>
                  <Descriptions.Item label="论文 ID">{result.fingerprint.paper_id}</Descriptions.Item>
                  <Descriptions.Item label="标题">{result.fingerprint.title}</Descriptions.Item>
                  <Descriptions.Item label="字符数">{result.fingerprint.text_char_count}</Descriptions.Item>
                  <Descriptions.Item label="画像">{result.fingerprint.profile_id}</Descriptions.Item>
                  <Descriptions.Item label="接收阈值">{result.fingerprint.accept_threshold}</Descriptions.Item>
                  <Descriptions.Item label="schema">{result.fingerprint.schema_version}</Descriptions.Item>
                </Descriptions>
                {Object.entries(result.document.sections).map(([name, content]) => (
                  <div key={name} style={{ marginTop: 12 }}><Text strong>{name}</Text><pre>{content}</pre></div>
                ))}
              </>,
            }]}
          />

          <Card title="实体与关系" style={{ marginTop: 16 }}>
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
              <Card title="学情诊断">
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
              <Card title="三智能体裁决">
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

          <Card title="个性化资源" style={{ marginTop: 16 }}>
            <ResourceSummary resources={result.resources} />
          </Card>
        </>
      )}
    </div>
  )
}
