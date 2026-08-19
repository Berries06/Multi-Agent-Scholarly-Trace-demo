import { useEffect, useState } from 'react'
import { ConfigProvider, Layout, Menu, Space, Tag, Typography } from 'antd'
import type { MenuProps } from 'antd'
import { getHealth } from './api'
import type { Health } from './types'
import LabPage from './LabPage'
import ProductPage from './ProductPage'
import { appTheme } from './theme'

const { Header, Sider, Content } = Layout
const { Title } = Typography

const menuItems: MenuProps['items'] = [
  { key: 'product', label: '产品演示' },
  { key: 'lab', label: '实验台 · 粘贴论文' },
]

export default function App() {
  const [mode, setMode] = useState('product')
  const [health, setHealth] = useState<Health | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => {})
  }, [])

  return (
    <ConfigProvider theme={appTheme}>
      <Layout style={{ minHeight: '100vh' }}>
        <Header
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            paddingInline: 24,
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Title level={4} style={{ color: '#4f46e5', margin: 0 }}>
            🧭 研海寻踪
          </Title>
          <Space size={4}>
            {health ? (
              <>
                <Tag color="green">后端在线</Tag>
                <Tag>{health.domain_count} 领域</Tag>
                <Tag>{health.system_agents} Agent</Tag>
              </>
            ) : (
              <Tag color="orange">连接中…</Tag>
            )}
          </Space>
        </Header>
        <Layout>
          <Sider
            width={208}
            theme="light"
            style={{ borderRight: '1px solid #f0f0f0', paddingTop: 12 }}
          >
            <Menu
              mode="inline"
              selectedKeys={[mode]}
              items={menuItems}
              onClick={(e) => setMode(e.key)}
              style={{ borderInlineEnd: 'none' }}
            />
          </Sider>
          <Content style={{ padding: 24, maxWidth: 1100, width: '100%', margin: '0 auto' }}>
            {mode === 'product' ? <ProductPage /> : <LabPage />}
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  )
}
