import { useEffect, useState } from 'react'
import { Button, Input, Select, Space, Tag, Tooltip, message } from 'antd'
import { getProviders, testProvider } from './api'
import type { LlmConfig, ProviderInfo } from './types'

interface Props {
  value: LlmConfig | null
  onChange: (value: LlmConfig | null) => void
}

const OFFLINE_VALUE = '__offline__'

export default function LlmModelSelector({ value, onChange }: Props) {
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [freeReady, setFreeReady] = useState(false)
  const [testing, setTesting] = useState(false)
  const [tested, setTested] = useState(false)

  useEffect(() => {
    getProviders()
      .then((data) => {
        setProviders(data.providers)
        setFreeReady(data.free_deepseek_ready)
      })
      .catch(() => {
        /* 供应商列表加载失败时保持离线规则模式 */
      })
  }, [])

  const selectedProviderId = value?.provider ?? OFFLINE_VALUE
  const selectedProvider = providers.find((p) => p.id === selectedProviderId)
  const requiresKey = selectedProvider?.requires_api_key ?? false
  const isFreeDeepseek = selectedProviderId === 'free-deepseek'

  const handleProviderChange = (providerId: string) => {
    setTested(false)
    if (providerId === OFFLINE_VALUE) {
      onChange(null)
      return
    }
    const meta = providers.find((p) => p.id === providerId)
    onChange({
      provider: providerId,
      model: meta?.default_model,
      api_key: '',
    })
  }

  const handleModelChange = (model: string) => {
    setTested(false)
    if (!value) return
    onChange({ ...value, model })
  }

  const handleKeyChange = (apiKey: string) => {
    setTested(false)
    if (!value) return
    onChange({ ...value, api_key: apiKey })
  }

  const handleTest = async () => {
    if (!value) return
    setTesting(true)
    try {
      const result = await testProvider(value)
      message.success(`连接成功（${Math.round(result.duration_ms ?? 0)} ms）`)
      setTested(true)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '连接测试失败')
      setTested(false)
    } finally {
      setTesting(false)
    }
  }

  const providerOptions = [
    { value: OFFLINE_VALUE, label: '离线规则引擎（无需 Key）' },
    ...providers.map((p) => ({
      value: p.id,
      label:
        p.id === 'free-deepseek'
          ? `${p.label}${p.available === false ? '（未就绪）' : '（服主托管免费）'}`
          : p.label,
      disabled: p.id === 'free-deepseek' && p.available === false,
    })),
  ]

  return (
    <div className="llm-selector">
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <label className="field-block">
          <span>决策引擎</span>
          <Select
            style={{ width: '100%' }}
            options={providerOptions}
            value={selectedProviderId}
            onChange={handleProviderChange}
          />
        </label>

        {value && selectedProvider && (
          <>
            <label className="field-block">
              <span>模型</span>
              <Select
                style={{ width: '100%' }}
                options={selectedProvider.models.map((m) => ({ value: m, label: m }))}
                value={value.model ?? selectedProvider.default_model}
                onChange={handleModelChange}
              />
            </label>

            {requiresKey && !isFreeDeepseek && (
              <label className="field-block">
                <span>API Key（仅本次请求使用，不入库）</span>
                <Input.Password
                  value={value.api_key ?? ''}
                  onChange={(e) => handleKeyChange(e.target.value)}
                  placeholder="sk-..."
                  autoComplete="off"
                />
              </label>
            )}

            {isFreeDeepseek && (
              <Tag color={freeReady ? 'green' : 'red'}>
                {freeReady ? '服主托管 Key 已就绪' : '服主未配置 Key，免费选项暂不可用'}
              </Tag>
            )}

            <Space>
              <Button
                size="small"
                onClick={handleTest}
                loading={testing}
                disabled={requiresKey && !isFreeDeepseek && !value.api_key}
              >
                测试连接
              </Button>
              {tested && (
                <Tag color="success">已通过</Tag>
              )}
              <Tooltip title="批判者与裁判 Agent 将使用所选 LLM；LLM 异常时自动回退规则基线并在 trace 中记录。">
                <Tag color="blue">LLM 裁决 + 规则护栏</Tag>
              </Tooltip>
            </Space>
          </>
        )}
      </Space>
    </div>
  )
}
