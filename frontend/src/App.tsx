import { lazy, Suspense, useEffect, useState } from 'react'
import { ConfigProvider } from 'antd'
import { getHealth } from './api'
import type { Health } from './types'
import { appTheme } from './theme'

const ExperimentPage = lazy(() => import('./ExperimentPage'))
const LabPage = lazy(() => import('./LabPage'))
const ProductPage = lazy(() => import('./ProductPage'))
const AtlasPage = lazy(() => import('./atlas/AtlasPage'))

type Workspace = 'product' | 'lab' | 'atlas' | 'experiments'

const workspaces: Array<{ key: Workspace; index: string; label: string; description: string }> = [
  { key: 'product', index: '01', label: '研究工作台', description: '问题、证据与裁决' },
  { key: 'lab', index: '02', label: '论文摄入', description: '抽取、复核与入图' },
  { key: 'atlas', index: '03', label: '证据图谱', description: '联动阅读 · 5 领域 290 篇' },
]

export default function App() {
  const [mode, setMode] = useState<Workspace>('product')
  const [health, setHealth] = useState<Health | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => {})
  }, [])

  return (
    <ConfigProvider theme={appTheme}>
      <div className="research-app">
        {mode !== 'atlas' && (
        <header className="masthead">
          <div className="masthead__edition">
            <span>CHALLENGE CUP · XH-202630</span>
            <span>21 AUGUST 2026</span>
          </div>
          <div className="masthead__identity">
            <div>
              <p className="eyebrow">EVIDENCE-GROUNDED RESEARCH INTELLIGENCE</p>
              <h1>研海寻踪</h1>
              <p className="masthead__subtitle">多智能体博弈推理的科研知识图谱发现系统</p>
            </div>
            <div className="system-proof" aria-live="polite">
              <span className={`system-proof__dot ${health ? 'is-online' : ''}`} />
              <div>
                <strong>{health ? '系统可用' : '正在连接'}</strong>
                <small>
                  {health
                    ? `${health.domain_count} 个领域 · ${health.core_agents ?? 3} 个核心 Agent`
                    : '等待证据服务响应'}
                </small>
              </div>
            </div>
          </div>
          <nav className="workspace-nav" aria-label="主要工作区">
            {workspaces.map((workspace) => (
              <button
                key={workspace.key}
                type="button"
                className={mode === workspace.key ? 'is-active' : ''}
                onClick={() => setMode(workspace.key)}
                aria-current={mode === workspace.key ? 'page' : undefined}
              >
                <span>{workspace.index}</span>
                <strong>{workspace.label}</strong>
                <small>{workspace.description}</small>
              </button>
            ))}
            <button
              type="button"
              className={mode === 'experiments' ? 'is-active' : ''}
              onClick={() => setMode('experiments')}
              aria-current={mode === 'experiments' ? 'page' : undefined}
            >
              <span>04</span>
              <strong>实验账本</strong>
              <small>复现、校验与对比</small>
            </button>
          </nav>
        </header>
        )}

        <main className={`research-main ${mode === 'atlas' ? 'research-main--atlas' : ''}`}>
          <Suspense fallback={<div className="ledger-loading">正在装载研究工作区</div>}>
            {mode === 'product' && <ProductPage />}
            {mode === 'lab' && <LabPage />}
            {mode === 'atlas' && <AtlasPage onExit={() => setMode('product')} />}
            {mode === 'experiments' && <ExperimentPage />}
          </Suspense>
        </main>

        {mode !== 'atlas' && (
        <footer className="research-footer">
          <span>研海寻踪 · YANHAI TRACE</span>
          <span>Evidence before assertion. Measurement before claim.</span>
        </footer>
        )}
      </div>
    </ConfigProvider>
  )
}
