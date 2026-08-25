import { lazy, Suspense, useEffect, useState } from 'react'
import { Alert, Button, ConfigProvider, Drawer, Form, Input, Space, Spin, Typography } from 'antd'
import { getAuth, getHealth, login, logout, updateProfile } from './api'
import type { AuthState, Health, LearnerProfile } from './types'
import { appTheme } from './theme'

const ExperimentPage = lazy(() => import('./ExperimentPage'))
const EvidenceAtlasPage = lazy(() => import('./EvidenceAtlasPage'))
const LabPage = lazy(() => import('./LabPage'))
const ProductPage = lazy(() => import('./ProductPage'))

type Workspace = 'product' | 'lab' | 'atlas' | 'experiments'

const workspaces: Array<{ key: Workspace; index: string; label: string; description: string }> = [
  { key: 'product', index: '01', label: '研究工作台', description: '问题、证据与裁决' },
  { key: 'lab', index: '02', label: '论文摄入', description: '抽取、复核与入图' },
  { key: 'atlas', index: '03', label: '证据图谱', description: '联动阅读与发现' },
  { key: 'experiments', index: '04', label: '实验账本', description: '复现、校验与对比' },
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
      .catch((error: Error) => { setAuth({ authenticated: false, user: null }); setAuthError(error.message) })
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
                <button key={workspace.key} type="button" className={mode === workspace.key ? 'is-active' : ''} onClick={() => setMode(workspace.key)}>
                  <span>{workspace.index}</span><strong>{workspace.label}</strong><small>{workspace.description}</small>
                </button>
              ))}
            </nav>
          )}
        </header>

        <main className="research-main">
          {auth === null ? <div className="login-gate"><Spin size="large" /></div> : !auth.authenticated ? (
            <section className="login-gate">
              <div className="login-gate__copy"><p className="section-index">MEMBER ACCESS</p><h2>登录后开始循证科研训练</h2><p>所有运行都会绑定账号并默认保存，便于复盘证据、画像变化和实验结果。公开注册已暂停，请联系服务器管理员创建账号。</p></div>
              <Form className="login-card" layout="vertical" onFinish={signIn}>
                <Typography.Title level={3}>成员登录</Typography.Title>
                <Form.Item label="邮箱或昵称" name="identifier" rules={[{ required: true }]}><Input autoComplete="username" /></Form.Item>
                <Form.Item label="密码" name="password" rules={[{ required: true, min: 8 }]}><Input.Password autoComplete="current-password" /></Form.Item>
                {authError && <Alert type="error" message={authError} showIcon />}
                <Button type="primary" htmlType="submit" loading={busy} block size="large">登录</Button>
                <Typography.Text type="secondary">账号仅能由服务器管理员创建，产品端不提供注册入口。</Typography.Text>
              </Form>
            </section>
          ) : (
            <Suspense fallback={<div className="ledger-loading">正在加载工作区…</div>}>
              {mode === 'product' && <ProductPage />}
              {mode === 'lab' && <LabPage />}
              {mode === 'atlas' && <EvidenceAtlasPage />}
              {mode === 'experiments' && <ExperimentPage />}
            </Suspense>
          )}
        </main>

        <footer className="research-footer"><span>研海寻踪 · YANHAI TRACE</span><span>证据先于断言，测量先于结论。</span></footer>
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
