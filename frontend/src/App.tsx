import { lazy, Suspense, useEffect, useState } from 'react'
import { Alert, Button, ConfigProvider, Drawer, Form, Input, Space, Typography } from 'antd'
import { getAuth, getHealth, login, logout, updateProfile } from './api'
import type { AuthState, Health, LearnerProfile } from './types'
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
  const [auth, setAuth] = useState<AuthState | null>(null)
  const [accountOpen, setAccountOpen] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    Promise.all([getHealth(), getAuth()])
      .then(([healthResult, authResult]) => { setHealth(healthResult); setAuth(authResult) })
      .catch(() => { setAuth({ authenticated: false, user: null }) })
  }, [])

  const signIn = async (values: { identifier: string; password: string }) => {
    setBusy(true); setAuthError(null)
    try { setAuth(await login(values.identifier, values.password)) }
    catch (error) { setAuthError(error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }

  const signOut = async () => {
    setAuth(await logout()); setAccountOpen(false); setMode('product')
  }

  const saveProfile = async (values: LearnerProfile) => {
    setBusy(true)
    try {
      if (!auth?.user) return
      const user = await updateProfile({ ...auth.user.profile, ...values })
      setAuth({ authenticated: true, user })
      setAccountOpen(false)
    } finally { setBusy(false) }
  }

  return (
    <ConfigProvider theme={appTheme}>
      <div className="research-app">
        {mode !== 'atlas' && (
        <header className="masthead">
          <div className="masthead__edition"><span>循证科研智能系统</span><span>统一产品版 · FASTAPI + REACT</span></div>
          <div className="masthead__identity">
            <div>
              <p className="eyebrow">EVIDENCE-GROUNDED RESEARCH INTELLIGENCE</p>
              <h1>研海寻踪</h1>
              <p className="masthead__subtitle">多智能体博弈推理的科研知识图谱与个性化训练系统</p>
            </div>
            <div className="masthead__account">
              <div className="system-proof" aria-live="polite">
                <span className={`system-proof__dot ${health ? 'is-online' : ''}`} />
                <div><strong>{health ? '系统可用' : '正在连接'}</strong><small>{health ? `${health.domain_count} 个领域 · ${health.core_agents} 个核心 Agent` : '等待服务响应'}</small></div>
              </div>
              {auth?.authenticated && <Button onClick={() => setAccountOpen(true)}>{auth.user?.nickname} · 我的账号</Button>}
            </div>
          </div>
          {auth?.authenticated && (
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
          )}
        </header>
        )}

        {auth === null ? (
          <main className="research-main"><div className="ledger-loading">正在连接服务…</div></main>
        ) : !auth.authenticated ? (
          <main className="research-main">
            <section className="login-gate">
              <div className="login-gate__copy">
                <p className="eyebrow">MEMBERS-ONLY RESEARCH WORKSPACE</p>
                <h2>科研工作台需要成员账号</h2>
                <p>研海寻踪以真实科研流程为基线：证据优先于断言，测量优先于主张。账号由团队管理员统一分配，请使用邮箱或昵称登录，所有检索、摄入、裁决与实验都会留痕可查。</p>
              </div>
              <div className="login-card">
                <Form layout="vertical" onFinish={signIn}>
                  <Form.Item label="邮箱或昵称" name="identifier" rules={[{ required: true, message: '请输入邮箱或昵称' }]}>
                    <Input autoFocus />
                  </Form.Item>
                  <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
                    <Input.Password />
                  </Form.Item>
                  {authError && <Alert type="error" showIcon message={authError} style={{ marginBottom: 16 }} />}
                  <Button type="primary" htmlType="submit" block loading={busy}>进入工作台</Button>
                </Form>
              </div>
            </section>
          </main>
        ) : (
        <main className={`research-main ${mode === 'atlas' ? 'research-main--atlas' : ''}`}>
          <Suspense fallback={<div className="ledger-loading">正在装载研究工作区</div>}>
            {mode === 'product' && <ProductPage />}
            {mode === 'lab' && <LabPage />}
            {mode === 'atlas' && <AtlasPage onExit={() => setMode('product')} />}
            {mode === 'experiments' && <ExperimentPage />}
          </Suspense>
        </main>
        )}

        {mode !== 'atlas' && (
        <footer className="research-footer">
          <span>研海寻踪 · YANHAI TRACE</span>
          <span>Evidence before assertion. Measurement before claim.</span>
        </footer>
        )}
      </div>

      {auth?.user && (
        <Drawer title="我的账号与画像" width={520} open={accountOpen} onClose={() => setAccountOpen(false)} extra={<Button danger onClick={signOut}>退出登录</Button>}>
          <Space direction="vertical" style={{ width: '100%' }}><Typography.Text>{auth.user.email}</Typography.Text><Typography.Text type="secondary">画像版本 v{auth.user.profile_version}</Typography.Text></Space>
          <Form layout="vertical" initialValues={auth.user.profile} onFinish={saveProfile} style={{ marginTop: 24 }}>
            <Form.Item label="显示名称" name="name" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item label="学习目标" name="goal" rules={[{ required: true, min: 3 }]}><Input.TextArea rows={3} /></Form.Item>
            <Form.Item label="教育背景" name="education"><Input /></Form.Item>
            <Form.Item label="当前角色" name="role"><Input /></Form.Item>
            <Form.Item label="偏好表达方式" name="preferred_style"><Input.TextArea rows={2} /></Form.Item>
            <Button type="primary" htmlType="submit" loading={busy}>保存为新画像版本</Button>
          </Form>
        </Drawer>
      )}
    </ConfigProvider>
  )
}
