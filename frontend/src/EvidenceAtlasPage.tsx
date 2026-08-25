import { useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Input, List, Row, Select, Space, Spin, Typography } from 'antd'
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

  return (
    <div className="research-page">
      <section className="page-lede page-lede--compact">
        <div><p className="section-index">03 / EVIDENCE ATLAS</p><h2>把知识图谱当作研究计算底座，而不是装饰图。</h2><p className="page-lede__summary">按领域查看论文、证据跨度、实体和裁决关系；每次图查询都返回可追溯的路径、推荐与后续问题。</p></div>
      </section>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
      <Card title="图谱问答与路径检索">
        <Space.Compact style={{ width: '100%' }}>
          <Select style={{ width: 280 }} value={domainId} options={domains.map((item) => ({ value: item.domain_id, label: item.domain_name }))} onChange={setDomainId} />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} onPressEnter={ask} />
          <Button type="primary" loading={loading} onClick={ask}>查询图谱</Button>
        </Space.Compact>
        {loading && <Spin style={{ marginTop: 20 }} />}
        {answer && <pre style={{ marginTop: 16 }}>{JSON.stringify(answer, null, 2)}</pre>}
      </Card>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col xs={24} xl={17}><Card title="全局证据图谱">{graph ? <KnowledgeGraphView data={graph} /> : <Paragraph type="secondary">正在加载图谱…</Paragraph>}</Card></Col>
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
