import { useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Collapse, Input, List, Row, Select, Spin, Typography } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { getDomains, getExtractedGraph, getHistory, queryGraph } from './api'
import KnowledgeGraphView from './KnowledgeGraphView'
import type { Domain, GraphData } from './types'

const { Paragraph, Text } = Typography

export default function EvidenceAtlasPage() {
  const [domains, setDomains] = useState<Domain[]>([])
  const [domainId, setDomainId] = useState<string>()
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [query, setQuery] = useState('哪些研究关系已经有原文证据，哪些仍需复核？')
  const [answer, setAnswer] = useState<Record<string, unknown> | null>(null)
  const [history, setHistory] = useState<Array<Record<string, unknown>>>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getDomains().then((items) => { setDomains(items); setDomainId(items[0]?.domain_id) }).catch((err: Error) => setError(err.message))
    getHistory().then(setHistory).catch(() => {})
  }, [])

  useEffect(() => {
    if (!domainId) return
    getExtractedGraph(domainId).then(setGraph).catch((err: Error) => setError(err.message))
  }, [domainId])

  const ask = async () => {
    setLoading(true); setError(null)
    try { setAnswer(await queryGraph({ query, domain_id: domainId })) }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setLoading(false) }
  }

  const answerBody = answer?.answer && typeof answer.answer === 'object' ? answer.answer as Record<string, unknown> : null
  const recommendedPapers = answer && Array.isArray(answer.recommended_papers)
    ? answer.recommended_papers.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    : []

  return (
    <div className="research-page">
      <section className="page-lede page-lede--simple">
        <div><h2>证据图谱</h2><p className="page-lede__summary">沿关系和原文证据追踪研究脉络。</p></div>
      </section>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
      <Card title="图谱问答与路径检索">
        <div className="graph-query-controls">
          <Select style={{ width: 280 }} value={domainId} options={domains.map((item) => ({ value: item.domain_id, label: item.domain_name }))} onChange={setDomainId} />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} onPressEnter={ask} />
          <Button icon={<SearchOutlined />} type="primary" loading={loading} onClick={ask}>查询</Button>
        </div>
        {loading && <Spin style={{ marginTop: 20 }} />}
        {answer && (
          <div className="graph-query-result">
            <Paragraph>{String(answerBody?.summary ?? '查询完成。')}</Paragraph>
            <List
              size="small"
              header={recommendedPapers.length ? '相关论文' : undefined}
              dataSource={recommendedPapers}
              renderItem={(paper) => <List.Item><List.Item.Meta title={String(paper.title ?? '未命名论文')} description={String(paper.recommendation_reason ?? '')} /></List.Item>}
            />
            <Collapse ghost items={[{ key: 'raw', label: '检索详情', children: <pre>{JSON.stringify(answer, null, 2)}</pre> }]} />
          </div>
        )}
      </Card>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col xs={24} xl={17}><Card title="关系网络">{graph ? <KnowledgeGraphView data={graph} /> : <Paragraph type="secondary">正在加载图谱…</Paragraph>}</Card></Col>
        <Col xs={24} xl={7}>
          <Card title="我的最近运行">
            <List dataSource={history} locale={{ emptyText: '尚无保存的运行' }} renderItem={(item) => (
              <List.Item><List.Item.Meta title={String(item.query ?? '未命名问题')} description={<><Text type="secondary">{String(item.domain_label ?? item.domain_slug ?? '')}</Text><br /><Text type="secondary">{String(item.created_at ?? '')}</Text></>} /></List.Item>
            )} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
