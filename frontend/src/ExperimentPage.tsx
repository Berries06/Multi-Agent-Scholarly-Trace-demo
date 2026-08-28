import { Alert, Button, Card, Empty, Spin, Tag } from 'antd'
import { ExperimentOutlined, LineChartOutlined } from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { getExperimentLedger } from './api'
import type { ExperimentLedger, ExperimentRun } from './types'

function RunCard({ run }: { run: ExperimentRun }) {
  return (
    <article className="run-record">
      <header>
        <div>
          <h3>{run.title}</h3>
        </div>
        <Tag color={run.status === 'passed' ? 'success' : 'error'}>{run.status}</Tag>
      </header>
      <dl>
        <div><dt>生成时间</dt><dd>{run.generated_at ? new Date(run.generated_at).toLocaleString('zh-CN') : '未知'}</dd></div>
        <div><dt>产物</dt><dd className="mono-value">{run.artifact_path}</dd></div>
      </dl>
    </article>
  )
}

export default function ExperimentPage() {
  const [ledger, setLedger] = useState<ExperimentLedger | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getExperimentLedger().then(setLedger).catch((reason: Error) => setError(reason.message))
  }, [])

  return (
    <section className="research-page ledger-page">
      <div className="page-lede page-lede--simple">
        <div><h2>实验账本</h2><p className="page-lede__summary">查看协议、运行状态与实验产物。</p></div>
      </div>

      {error && <Alert type="error" showIcon message="实验账本读取失败" description={error} />}
      {!ledger && !error && <div className="ledger-loading"><Spin /><span>正在核验运行目录</span></div>}

      {ledger && (
        <>
          <Card className="protocol-card" variant="outlined">
            <div className="protocol-card__intro">
              <h3><ExperimentOutlined /> 复现实验</h3>
            </div>
            <code className="run-command">{ledger.run_command}</code>
            <div className="mlflow-bridge">
              <strong>参数、指标与运行对比</strong>
              <Button icon={<LineChartOutlined />} type="primary" href={ledger.mlflow_url} target="_blank" rel="noreferrer">
                实验追踪
              </Button>
            </div>
            <div className="protocol-grid">
              {ledger.protocols.map((protocol, index) => (
                <article key={protocol.slug}>
                  <span>{String(index + 1).padStart(2, '0')}</span>
                  <h4>{protocol.title}</h4>
                  <small>{protocol.primary_metrics.slice(0, 3).join(' · ')}</small>
                </article>
              ))}
            </div>
          </Card>

          <div className="ledger-section-heading">
            <h3>运行记录 · {ledger.run_count}</h3>
          </div>
          {ledger.runs.length ? (
            <div className="run-grid">{ledger.runs.map((run) => <RunCard key={run.run_id} run={run} />)}</div>
          ) : (
            <Empty description="尚无已验证运行。执行上方命令后刷新页面。" />
          )}
        </>
      )}
    </section>
  )
}
