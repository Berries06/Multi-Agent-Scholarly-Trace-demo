import { useEffect, useState } from 'react'
import { Alert, Button, ConfigProvider, Drawer, Form, Input, Space, Tag, Typography } from 'antd'
import { LoginOutlined, UserAddOutlined, UserOutlined } from '@ant-design/icons'
import { bootstrapAccount, getAuth, getAuthStatus, getHealth, login, logout, registerAccount, updateProfile } from './api'
import type { AuthState, Health, LearnerProfile } from './types'
import { appTheme } from './theme'
import { Shell } from './app/Shell'
import { LibraryPage } from './app/DataPages'
import { BuildGraphPage, EvidenceCenterPage, ProjectGraphPage } from './app/BuildGraph'
import { LabPage } from './app/LabPage'
import { FindingsPage, ProjectOverviewPage, ProjectSettingsPage } from './app/ProjectPages'
import { ResearchPage } from './app/RunPages'
import { ProjectProvider } from './app/project'
import { DEFAULT_SECTION, hashFor, sectionFromHash, type Section } from './app/data'

export default function App() {
  const [section, setSection] = useState<Section>(() =>
    typeof window === 'undefined' ? DEFAULT_SECTION : sectionFromHash(window.location.hash),
  )
  const [health, setHealth] = useState<Health | null>(null)
  const [auth, setAuth] = useState<AuthState | null>(null)
  const [firstRun, setFirstRun] = useState(false)
  const [registrationOpen, setRegistrationOpen] = useState(false)
  const [registering, setRegistering] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    Promise.all([getHealth(), getAuth()])
      .then(([healthResult, authResult]) => { setHealth(healthResult); setAuth(authResult) })
      .catch(() => { setAuth({ authenticated: false, user: null }) })
    getAuthStatus()
      .then((status) => {
        setFirstRun(!status.has_users)
        setRegistrationOpen(Boolean(status.registration_open))
      })
      .catch(() => setFirstRun(false))
  }, [])

  const go = (next: Section) => {
    setSection(next)
    if (typeof window !== 'undefined' && window.location.hash !== hashFor(next)) {
      window.history.replaceState(null, '', hashFor(next))
    }
  }

  useEffect(() => {
    if (typeof window === 'undefined') return
    const sync = () => setSection(sectionFromHash(window.location.hash))
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])

  const signIn = async (values: { identifier: string; password: string }) => {
    setBusy(true); setAuthError(null)
    try { setAuth(await login(values.identifier, values.password)) }
    catch (error) { setAuthError(error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }

  const registerAccountNow = async (values: { email: string; nickname: string; password: string }) => {
    setBusy(true); setAuthError(null)
    try { setAuth(await registerAccount(values)) }
    catch (error) { setAuthError(error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }

  const createAccount = async (values: { email: string; nickname: string; password: string }) => {
    setBusy(true); setAuthError(null)
    try { setAuth(await bootstrapAccount(values)); setFirstRun(false) }
    catch (error) { setAuthError(error instanceof Error ? error.message : String(error)) }
    finally { setBusy(false) }
  }

  const signOut = async () => {
    await logout(); setAuth({ authenticated: false, user: null }); setAccountOpen(false); go(DEFAULT_SECTION)
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

  if (auth === null) {
    return <div className="content"><p className="note">正在连接服务…</p></div>
  }

  if (!auth.authenticated) {
    return (
      <ConfigProvider theme={appTheme}>
        <div className="content" style={{ maxWidth: 720, margin: '0 auto', paddingTop: 72 }}>
          <header className="page-head">
            <div>
              <h1>研海寻踪</h1>
              <p>用你自己的论文建一份能回到原文的知识图谱。</p>
            </div>
          </header>
          <div className="panel">
            <div className="panel__body">
              {firstRun ? (
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18, flexWrap: 'wrap' }}>
                    <Tag color="gold" style={{ marginInlineEnd: 0 }}>第一次用</Tag>
                    <span className="note">这台机器上还没有账号。建一个，之后就用它登录。</span>
                  </div>
                  <Form layout="vertical" onFinish={createAccount}>
                    <Form.Item label="邮箱" name="email" rules={[{ required: true, type: 'email', message: '请填写邮箱' }]}>
                      <Input autoFocus autoComplete="email" placeholder="you@example.com" />
                    </Form.Item>
                    <Form.Item label="称呼" name="nickname" rules={[{ required: true, min: 2, message: '请填写至少 2 个字的称呼' }]}>
                      <Input autoComplete="nickname" placeholder="别人怎么称呼你" />
                    </Form.Item>
                    <Form.Item label="密码" name="password" rules={[{ required: true, min: 8, message: '请设置至少 8 位密码' }]}>
                      <Input.Password autoComplete="new-password" />
                    </Form.Item>
                    {authError && <Alert type="error" showIcon message={authError} style={{ marginBottom: 16 }} />}
                    <Button icon={<UserAddOutlined />} type="primary" htmlType="submit" block loading={busy}>
                      创建并进入
                    </Button>
                  </Form>
                </>
              ) : registering ? (
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18, flexWrap: 'wrap' }}>
                    <Tag color="gold" style={{ marginInlineEnd: 0 }}>注册</Tag>
                    <span className="note">建好账号会直接登录。</span>
                  </div>
                  <Form layout="vertical" onFinish={registerAccountNow}>
                    <Form.Item label="邮箱" name="email" rules={[{ required: true, type: 'email', message: '请填写邮箱' }]}>
                      <Input autoFocus autoComplete="email" placeholder="you@example.com" />
                    </Form.Item>
                    <Form.Item label="称呼" name="nickname" rules={[{ required: true, min: 2, message: '请填写至少 2 个字的称呼' }]}>
                      <Input autoComplete="nickname" placeholder="别人怎么称呼你" />
                    </Form.Item>
                    <Form.Item label="密码" name="password" rules={[{ required: true, min: 8, message: '请设置至少 8 位密码' }]}>
                      <Input.Password autoComplete="new-password" />
                    </Form.Item>
                    {authError && <Alert type="error" showIcon message={authError} style={{ marginBottom: 16 }} />}
                    <Button icon={<UserAddOutlined />} type="primary" htmlType="submit" block loading={busy}>
                      注册并登录
                    </Button>
                  </Form>
                  <button
                    type="button"
                    className="btn btn--quiet btn--sm"
                    style={{ marginTop: 12 }}
                    onClick={() => { setRegistering(false); setAuthError(null) }}
                  >
                    已有账号，去登录
                  </button>
                </>
              ) : (
                <>
                  <Form layout="vertical" onFinish={signIn}>
                    <Form.Item label="邮箱或昵称" name="identifier" rules={[{ required: true, message: '请输入邮箱或昵称' }]}>
                      <Input autoFocus autoComplete="username" />
                    </Form.Item>
                    <Form.Item label="密码" name="password" rules={[{ required: true, min: 8, message: '请输入至少 8 位密码' }]}>
                      <Input.Password autoComplete="current-password" />
                    </Form.Item>
                    {authError && <Alert type="error" showIcon message={authError} style={{ marginBottom: 16 }} />}
                    <Button icon={<LoginOutlined />} type="primary" htmlType="submit" block loading={busy}>
                      进入工作台
                    </Button>
                  </Form>
                  {registrationOpen ? (
                    <button
                      type="button"
                      className="btn btn--quiet btn--sm"
                      style={{ marginTop: 12 }}
                      onClick={() => { setRegistering(true); setAuthError(null) }}
                    >
                      没有账号？注册一个
                    </button>
                  ) : (
                    <p className="note" style={{ marginTop: 12 }}>账号由管理员分配，暂不开放注册。</p>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </ConfigProvider>
    )
  }

  const page = (() => {
    switch (section) {
      case 'workbench':
        return <ResearchPage />
      case 'library':
        return <LibraryPage />
      case 'build':
        return <BuildGraphPage />
      case 'graph':
        return <ProjectGraphPage />
      case 'evidence':
        return <EvidenceCenterPage />
      case 'findings':
        return <FindingsPage onNavigate={(next) => go(next as Section)} />
      case 'settings':
        return <ProjectSettingsPage />
      case 'lab':
        return <LabPage />
      case 'overview':
      default:
        return <ProjectOverviewPage onNavigate={(next) => go(next as Section)} />
    }
  })()

  return (
    <ConfigProvider theme={appTheme}>
      <ProjectProvider enabled>
        <Shell
          active={section}
          onNavigate={go}
          health={health}
          account={auth.user?.nickname ?? '账号'}
          onAccount={() => setAccountOpen(true)}
        >
          {page}
        </Shell>
      </ProjectProvider>

      {auth.user && (
        <Drawer
          title="我的账号与画像"
          width={520}
          open={accountOpen}
          onClose={() => setAccountOpen(false)}
          extra={<Button danger onClick={signOut}>退出登录</Button>}
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            <Typography.Text>{auth.user.email}</Typography.Text>
            <Typography.Text type="secondary">画像版本 v{auth.user.profile_version}</Typography.Text>
          </Space>
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
      <span style={{ display: 'none' }}><UserOutlined /></span>
    </ConfigProvider>
  )
}
