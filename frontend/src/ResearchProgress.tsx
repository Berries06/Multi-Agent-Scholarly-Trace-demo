import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BulbOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  CloseCircleFilled,
  FileSearchOutlined,
  LoadingOutlined,
  QuestionCircleOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  WarningFilled,
} from '@ant-design/icons'
import { Collapse, Progress, Steps, Tag, Typography } from 'antd'
import type { ResearchProgressDetail, ResearchProgressEvent, RunResult } from './types'

const { Text } = Typography

const ONLINE_PHASES = [
  ['baseline', '理解问题'],
  ['planning', '规划检索'],
  ['retrieval', '证据检索'],
  ['proposal', '命题生成'],
  ['review', '批判裁决'],
  ['validation', '完整性检查'],
  ['persistence', '保存结果'],
] as const

const OFFLINE_PHASES = [
  ['diagnosis', '学情诊断'],
  ['intent', '意图识别'],
  ['graph_retrieval', '图谱检索'],
  ['retrieval', '证据检索'],
  ['extraction', '索引检查'],
  ['proposal', '命题生成'],
  ['critique', '反证检查'],
  ['adjudication', '置信裁决'],
  ['resources', '资源生成'],
  ['persistence', '保存结果'],
] as const

function formatDuration(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.round(milliseconds / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function eventIcon(state: ResearchProgressEvent['state']) {
  if (state === 'completed') return <CheckCircleFilled className="progress-event__icon is-complete" />
  if (state === 'running') return <LoadingOutlined className="progress-event__icon is-running" />
  if (state === 'retrying' || state === 'insufficient' || state === 'degraded') return <WarningFilled className="progress-event__icon is-warning" />
  if (state === 'failed') return <CloseCircleFilled className="progress-event__icon is-failed" />
  return <ClockCircleOutlined className="progress-event__icon" />
}

function detailIcon(kind: ResearchProgressDetail['kind']) {
  if (kind === 'query') return <SearchOutlined />
  if (kind === 'question') return <QuestionCircleOutlined />
  if (kind === 'evidence') return <FileSearchOutlined />
  if (kind === 'claim') return <BulbOutlined />
  return <SafetyCertificateOutlined />
}

function statusLabel(status?: string) {
  return ({
    ready: '已生成',
    selected: '已选入',
    proposed: '待批判',
    accepted: '接受',
    review: '待复核',
    rejected: '拒绝',
  } as Record<string, string>)[status ?? ''] ?? status
}

interface ResearchProgressProps {
  events: ResearchProgressEvent[]
  running: boolean
  mode: 'offline' | 'online'
  operationId: string
  startedAt: number | null
  lastSignalAt: number | null
  result?: RunResult | null
  error?: string | null
}

export default function ResearchProgress({
  events,
  running,
  mode,
  operationId,
  startedAt,
  lastSignalAt,
  result,
  error,
}: ResearchProgressProps) {
  const [now, setNow] = useState(Date.now())
  const eventListRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!running) return undefined
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [running])

  useEffect(() => {
    if (!running || !eventListRef.current) return
    eventListRef.current.scrollTop = eventListRef.current.scrollHeight
  }, [events.length, running])

  const latest = events[events.length - 1]
  const latestArtifact = [...events].reverse().find((event) => event.details?.length)
  const latestByPhase = useMemo(() => {
    const values = new Map<string, ResearchProgressEvent>()
    for (const event of events) values.set(event.phase, event)
    return values
  }, [events])
  const phases = mode === 'online' ? ONLINE_PHASES : OFFLINE_PHASES
  const failed = Boolean(error) || events.some((event) => event.state === 'failed')
  const degraded = Boolean(result?.provider_run?.degraded) || events.some((event) => event.state === 'degraded')
  const insufficient = events.some((event) => event.state === 'insufficient')
  const nonFailedPercent = Math.max(1, ...events.filter((event) => event.state !== 'failed').map((event) => event.percent))
  const percent = running ? Math.min(nonFailedPercent, 99) : failed ? Math.min(nonFailedPercent, 99) : 100
  const elapsedMs = running
    ? Math.max(0, now - (startedAt ?? now))
    : Number(result?.observability?.duration_ms ?? latest?.elapsed_ms ?? 0)
  const connectionFresh = !running || !lastSignalAt || now - lastSignalAt < 20_000

  if (!running) {
    const stateClass = failed ? 'is-failed' : degraded ? 'is-degraded' : insufficient ? 'is-insufficient' : 'is-complete'
    const title = failed
      ? '研究任务未完成'
      : degraded
        ? '已使用离线安全基线完成'
        : insufficient
          ? '研究完成，但当前证据不足'
          : '研究任务已完成'
    const callCount = result?.provider_run?.calls?.length ?? 0
    const retries = result?.provider_run?.calls?.reduce((sum, call) => sum + Math.max(0, (call.attempts ?? 1) - 1), 0) ?? 0
    return (
      <div className={`research-progress-summary ${stateClass}`} aria-live="polite">
        <div className="research-progress-summary__title">
          {failed ? <CloseCircleFilled /> : degraded || insufficient ? <WarningFilled /> : <CheckCircleFilled />}
          <strong>{title}</strong>
        </div>
        <div className="research-progress-summary__facts">
          <span>{formatDuration(elapsedMs)}</span>
          {callCount > 0 && <span>{callCount} 次模型调用</span>}
          {retries > 0 && <span>{retries} 次自动重试</span>}
          {result && <span>{result.claims.length} 条命题</span>}
        </div>
      </div>
    )
  }

  return (
    <section className="research-progress" aria-live="polite" aria-busy="true">
      <div className="research-progress__header">
        <div>
          <div className="research-progress__eyebrow">AI 处理过程</div>
          <h3>{latest?.title ?? '正在建立运行连接'}</h3>
          <Text type="secondary">{latest?.message ?? '正在启动研究任务并确认服务连接。'}</Text>
        </div>
        <div className="research-progress__clock">
          <strong>{percent}%</strong>
          <span>{formatDuration(elapsedMs)}</span>
        </div>
      </div>

      <Progress
        className="research-progress__bar"
        percent={percent}
        showInfo={false}
        status={failed ? 'exception' : 'active'}
        strokeColor={latest?.state === 'retrying' ? '#d97706' : '#2563eb'}
      />

      <Steps
        className="research-progress__steps"
        responsive
        size="small"
        items={phases.map(([phase, title]) => {
          const event = latestByPhase.get(phase)
          const status: 'finish' | 'process' | 'error' | 'wait' = event?.state === 'completed'
            ? 'finish'
            : event?.state === 'running' || event?.state === 'retrying'
              ? 'process'
              : event && ['failed', 'degraded', 'insufficient'].includes(event.state)
                ? 'error'
                : 'wait'
          return { title, status }
        })}
      />

      <div className="research-progress__connection">
        <span className={`connection-dot ${connectionFresh ? 'is-live' : ''}`} />
        {connectionFresh ? '连接正常' : '正在等待服务器事件'}
        <span>·</span>
        <span>进度来自真实阶段事件</span>
      </div>

      <div className="research-progress__workspace">
        <section className="progress-artifact">
          <div className="progress-panel-heading">
            <div>
              <span>LATEST AGENT OUTPUT</span>
              <strong>最新 Agent 产物</strong>
            </div>
            {latestArtifact?.content_origin === 'model' && <Tag color="purple">模型即时生成</Tag>}
            {latestArtifact?.content_origin === 'retrieval' && <Tag color="blue">实时证据</Tag>}
          </div>
          {latestArtifact ? (
            <>
              <p className="progress-artifact__summary">{latestArtifact.message}</p>
              <div className="progress-artifact__list">
                {latestArtifact.details?.map((detail, index) => (
                  <div className={`progress-artifact__item is-${detail.kind}`} key={`${detail.reference ?? detail.label}-${index}`}>
                    <span className="progress-artifact__index">{String(index + 1).padStart(2, '0')}</span>
                    <span className="progress-artifact__icon">{detailIcon(detail.kind)}</span>
                    <div>
                      <strong>{detail.label}</strong>
                      {detail.meta && <small>{detail.meta}</small>}
                    </div>
                    {detail.status && <Tag>{statusLabel(detail.status)}</Tag>}
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="progress-artifact__empty">
              <LoadingOutlined />
              <strong>等待首个可验证产物</strong>
              <span>检索式、证据来源、候选命题会在生成后逐项出现在这里。</span>
            </div>
          )}
        </section>

        <section className="progress-activity">
          <div className="progress-panel-heading">
            <div><span>LIVE ACTIVITY</span><strong>阶段活动</strong></div>
            <Tag>{events.length} 条</Tag>
          </div>
          <div className="progress-event-list" ref={eventListRef}>
            {events.map((event) => (
              <div className={`progress-event is-${event.state}`} key={event.sequence}>
                {eventIcon(event.state)}
                <div>
                  <div className="progress-event__title">
                    <strong>{event.title}</strong>
                    {event.state === 'retrying' && <Tag color="orange">自动重试</Tag>}
                    {event.state === 'degraded' && <Tag color="orange">已降级</Tag>}
                    {event.state === 'insufficient' && <Tag color="gold">证据不足</Tag>}
                  </div>
                  <div className="progress-event__message">{event.message}</div>
                  {event.details && event.details.length > 0 && <span className="progress-event__count">{event.details.length} 项产物</span>}
                  {event.elapsed_ms !== undefined && <span className="progress-event__time">{formatDuration(event.elapsed_ms)}</span>}
                </div>
              </div>
            ))}
            {events.length === 0 && (
              <div className="progress-event is-running">
                <LoadingOutlined className="progress-event__icon is-running" />
                <div><strong>正在建立运行连接</strong><div className="progress-event__message">服务正在创建本次研究操作。</div></div>
              </div>
            )}
          </div>
        </section>
      </div>

      <div className="research-progress__note">“模型即时生成”表示直接来自本轮结构化模型输出；界面展示可验证产物，不展示隐藏思维链。</div>
      {operationId && (
        <Collapse
          ghost
          size="small"
          className="research-progress__details"
          items={[{ key: 'operation', label: '技术详情', children: <Text code>{operationId}</Text> }]}
        />
      )}
    </section>
  )
}
