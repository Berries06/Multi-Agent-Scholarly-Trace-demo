import { Layout, Tabs, Typography } from 'antd'
import LabPage from './LabPage'
import ProductPage from './ProductPage'

const { Header, Content } = Layout
const { Title } = Typography

export default function App() {
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center' }}>
        <Title level={4} style={{ color: '#fff', margin: 0 }}>
          🧭 研海寻踪 · 领域知识个性化生成与多智能体协同决策
        </Title>
      </Header>
      <Content style={{ padding: 24 }}>
        <div style={{ maxWidth: 1240, margin: '0 auto' }}>
          <Tabs
            defaultActiveKey="product"
            size="large"
            items={[
              { key: 'product', label: '产品演示', children: <ProductPage /> },
              { key: 'lab', label: '实验台（粘贴论文）', children: <LabPage /> },
            ]}
          />
        </div>
      </Content>
    </Layout>
  )
}
