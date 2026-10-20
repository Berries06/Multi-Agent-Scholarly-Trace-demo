import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Modal } from 'antd'
import { createDomain, deleteDomain, getDomains } from '../api'
import type { Domain } from '../types'

/** 领域选择器原来的样子。内置五个都绑着仓库里的样本文献，
 *  用户真实的研究方向往往不在这五个里面，所以下面这套东西把「自己起一个领域」
 *  做进了下拉框：选到最后一项就地新建，建完自动选中。 */

export const NEW_DOMAIN_VALUE = '__new_domain__'

export interface DomainOption {
  id: string
  name: string
  custom: boolean
  corpusReady: boolean
  description: string
}

function toOption(domain: Domain): DomainOption {
  return {
    id: domain.domain_id,
    name: domain.domain_name,
    custom: Boolean(domain.is_custom),
    corpusReady: domain.corpus_ready !== false,
    description: String(domain.description ?? ''),
  }
}

export interface DomainState {
  domains: DomainOption[]
  selected: DomainOption | null
  domainId: string
  setDomainId: (next: string) => void
  loading: boolean
  error: string | null
  reload: () => Promise<void>
  create: (domainName: string, description: string) => Promise<DomainOption | null>
  remove: (domainId: string) => Promise<void>
}

/** 拿一遍领域列表，并记住当前选的是哪个。
 *
 *  - 默认选第一个有语料的领域（不是第一个自定义的）；
 *  - 选中的领域被删掉后自动退回有语料的那个，不留下一个指向空处的 id。
 */
export function useDomains(): DomainState {
  const [domains, setDomains] = useState<DomainOption[]>([])
  const [domainId, setDomainIdState] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // 当前选中的 id 另存一份在 ref 里：`apply` 要读它，但不能因为它的变化而重建，
  // 否则 `reload` 变 → 拉列表的 effect 重跑 → 无限刷新。
  const currentId = useRef('')

  const setDomainId = useCallback((next: string) => {
    currentId.current = next
    setDomainIdState(next)
  }, [])

  const apply = useCallback((items: DomainOption[], keep?: string) => {
    setDomains(items)
    const wanted = keep ?? currentId.current
    const fallback = items.find((item) => item.corpusReady) ?? items[0]
    const next = items.find((item) => item.id === wanted) ?? fallback
    setDomainId(next ? next.id : '')
  }, [setDomainId])

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const items = (await getDomains()).map(toOption)
      apply(items)
      setError(null)
    } catch (err) {
      setDomains([])
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [apply])

  useEffect(() => { void reload() }, [reload])

  const create = useCallback(async (domainName: string, description: string) => {
    const created = await createDomain({ domain_name: domainName, description })
    const option = toOption(created)
    setDomains((list) => [...list.filter((item) => item.id !== option.id), option])
    setDomainId(option.id)
    return option
  }, [setDomainId])

  const remove = useCallback(async (target: string) => {
    await deleteDomain(target)
    setDomains((list) => {
      const rest = list.filter((item) => item.id !== target)
      if (target === currentId.current) {
        const fallback = rest.find((item) => item.corpusReady) ?? rest[0]
        setDomainId(fallback ? fallback.id : '')
      }
      return rest
    })
  }, [setDomainId])

  const selected = useMemo(
    () => domains.find((item) => item.id === domainId) ?? null,
    [domains, domainId],
  )

  return { domains, selected, domainId, setDomainId, loading, error, reload, create, remove }
}

/** 一个下拉框，末尾带「新建研究领域…」。
 *
 *  选中最后那一项不会真的选中它，而是弹窗让人填名字；填完立刻建、建完自动选上。
 */
export function DomainSelect({
  state,
  label = '研究领域',
  allowCreate = true,
}: {
  state: DomainState
  label?: string
  allowCreate?: boolean
}) {
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const custom = state.domains.filter((item) => item.custom)

  const open = () => {
    setName('')
    setDescription('')
    setMessage(null)
    setCreating(true)
  }

  const submit = async () => {
    const trimmed = name.trim()
    if (trimmed.length < 2) {
      setMessage('领域名称请填 2 到 40 个字。')
      return
    }
    setBusy(true)
    try {
      await state.create(trimmed, description.trim())
      setCreating(false)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <label className="field">
        <span>{label}</span>
        <select
          value={state.domainId}
          onChange={(event) => {
            if (event.target.value === NEW_DOMAIN_VALUE) {
              open()
              return
            }
            state.setDomainId(event.target.value)
          }}
        >
          {custom.length > 0 && (
            <optgroup label="我自己的领域">
              {custom.map((domain) => (
                <option key={domain.id} value={domain.id}>{domain.name}</option>
              ))}
            </optgroup>
          )}
          {allowCreate && (
            <option value={NEW_DOMAIN_VALUE}>＋ 新建研究领域…</option>
          )}
        </select>
      </label>

      <Modal
        open={creating}
        title="新建研究领域"
        okText="建好并选中"
        cancelText="先不建"
        confirmLoading={busy}
        onOk={() => void submit()}
        onCancel={() => setCreating(false)}
        okButtonProps={{ disabled: name.trim().length < 2 }}
      >
        <div style={{ display: 'grid', gap: 12 }}>
          <label className="field">
            <span>领域名称</span>
            <input
              value={name}
              autoFocus
              maxLength={40}
              placeholder="例如：蛋白质相分离与凝胶化"
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="field">
            <span>一句话说明（可选）</span>
            <input
              value={description}
              maxLength={200}
              placeholder="这个方向你在研究什么"
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <p className="note" style={{ margin: 0 }}>
            用它给课题、论文和线索归个类。建好后自动选中。
          </p>
          {message ? <p className="note" style={{ color: 'var(--danger)', margin: 0 }}>{message}</p> : null}
        </div>
      </Modal>
    </>
  )
}

/** 兼容旧页面：语料已经下架，这个提示不再显示内容。 */
export function CorpusNote(_: { state: DomainState }) {
  return null
}
