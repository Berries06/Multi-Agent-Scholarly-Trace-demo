import { Alert, Button, Card, Empty, Spin, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { getExperimentLedger } from './api'
import type { ExperimentLedger, ExperimentRun } from './types'

function compactHash(value: string | null) {
  return value ? value.slice(0, 10) : '未记录'
}

function RunCard({ run }: { run: ExperimentRun }) {
  return (
    <article className="run-record">
      <header>
        <div>
          <span className="run-record__status">{run.status === 'passed' ? 'VERIFIED RUN' : 'INVALID RUN'}</span>
          <h3>{run.title}</h3>
        </div>
        <Tag color={run.status === 'passed' ? 'success' : 'error'}>{run.status}</Tag>
      </header>
      <dl>
        <div><dt>评估性质</dt><dd>{run.evaluation_type}</dd></div>
        <div><dt>生成时间</dt><dd>{run.generated_at ? new Date(run.generated_at).toLocaleString('zh-CN') : '未知'}</dd></div>
        <div><dt>Git</dt><dd className="mono-value">{compactHash(run.git_head)}{run.git_dirty ? ' · dirty' : ''}</dd></div>
        <div><dt>产物</dt><dd className="mono-value">{run.artifact_path}</dd></div>
      </dl>
      {run.summary.length > 0 && (
        <p className="run-record__note">{run.summary.length} 组汇总结果；原始案例、配置和验证收据保存在同一运行目录。</p>
      )}
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
      <div className="page-lede page-lede--compact">
        <div>
          <p className="section-index">04 / EXPERIMENT LEDGER</p>
          <h2>每个数字，都能回到一次运行。</h2>
          <p className="page-lede__summary">
            协议、输入、代码、环境、原始输出和验证收据共同定义实验。这里展示的是磁盘产物的只读投影，不允许页面状态替代研究事实。
          </p>
        </div>
        <dl className="method-facts">
          <div><dt>冻结协议</dt><dd>{ledger?.protocol_count ?? '—'}</dd></div>
          <div><dt>已登记运行</dt><dd>{ledger?.run_count ?? '—'}</dd></div>
          <div><dt>主张状态</dt><dd className="is-pending">PROXY / 待真人金标</dd></div>
        </dl>
      </div>

      {error && <Alert type="error" showIcon message="实验账本读取失败" description={error} />}
      {!ledger && !error && <div className="ledger-loading"><Spin /><span>正在核验运行目录</span></div>}

      {ledger && (
        <>
          <Card className="protocol-card" variant="outlined">
            <div className="protocol-card__intro">
              <div>
                <span className="card-kicker">PUBLIC REPRODUCTION PROTOCOL</span>
                <h3>从普通终端或 DSH 运行同一协议</h3>
              </div>
              <p>当前结果均受各协议的 claim ceiling 限制；确定性重放不能当作独立样本。</p>
            </div>
            <code className="run-command">{ledger.run_command}</code>
            <div className="mlflow-bridge">
              <div>
                <span className="card-kicker">INTERNAL TRACKING BACKEND</span>
                <strong>MLflow 管理参数、指标、制品和跨运行对比</strong>
                <small>研海寻踪的验证目录仍是实验事实源；MLflow 是可搜索的内部投影。</small>
              </div>
              <Button type="primary" href={ledger.mlflow_url} target="_blank" rel="noreferrer">
                打开 MLflow
              </Button>
            </div>
            <div className="protocol-grid">
              {ledger.protocols.map((protocol, index) => (
                <article key={protocol.slug}>
                  <span>{String(index + 1).padStart(2, '0')}</span>
                  <h4>{protocol.title}</h4>
                  <p>{protocol.purpose}</p>
                  <small>{protocol.evaluation_type} · {protocol.mode}</small>
                </article>
              ))}
            </div>
          </Card>

          <div className="ledger-section-heading">
            <div><span className="card-kicker">VERIFIED ARTIFACTS</span><h3>运行记录</h3></div>
            <p>仅发现含 verification.json 的目录才进入账本。</p>
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
