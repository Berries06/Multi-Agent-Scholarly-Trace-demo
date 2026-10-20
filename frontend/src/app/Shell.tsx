import type { ReactNode } from 'react'
import brandMark from '../assets/multi-agent-mark.png'
import { SECTIONS, SECTION_GROUPS, labelOf, type Section } from './data'
import { useProject } from './project'
import type { Health } from '../types'

/** 全站唯一的外壳：左侧栏（品牌 + 课题切换 + 八个工作区）+ 顶部工具条 + 内容区。 */
export function Shell({
  active,
  onNavigate,
  health,
  account,
  onAccount,
  children,
}: {
  active: Section
  onNavigate: (section: Section) => void
  health: Health | null
  account: string
  onAccount: () => void
  children: ReactNode
}) {
  const { projects, active: project, select, loading, error } = useProject()

  return (
    <div className="shell">
      <aside className="side">
        <div className="side__brand">
          <img src={brandMark} alt="研海寻踪" />
          <div>
            <strong>研海寻踪</strong>
            <span>YANHAI TRACE</span>
          </div>
        </div>

        <label className="side__project">
          <span>当前课题</span>
          <select
            value={project?.project_id ?? ''}
            onChange={(event) => select(event.target.value)}
            disabled={loading || projects.length === 0}
            aria-label="切换研究课题"
          >
            {projects.length === 0 ? (
              <option value="">{loading ? '正在读取…' : '还没有课题'}</option>
            ) : (
              projects.map((item) => (
                <option key={item.project_id} value={item.project_id}>
                  {item.name}
                </option>
              ))
            )}
          </select>
          {error ? <em>课题读取失败：{error}</em> : null}
        </label>

        <nav aria-label="工作区">
          {SECTION_GROUPS.map((group) => (
            <div className="side__group" key={group.title}>
              <p>{group.title}</p>
              {group.keys.map((key) => {
                const meta = SECTIONS.find((item) => item.key === key)
                if (!meta) return null
                // 构建图谱上挂一个待办数：一眼看出还有多少条没审
                const pending =
                  key === 'build'
                    ? Math.max(0, (project?.relation_count ?? 0) - (project?.decided_count ?? 0))
                    : 0
                return (
                  <button
                    key={key}
                    type="button"
                    className={`side__item${active === key ? ' is-active' : ''}`}
                    onClick={() => onNavigate(key)}
                    aria-current={active === key ? 'page' : undefined}
                    title={meta.hint}
                  >
                    <span>{meta.label}</span>
                    {pending > 0 ? <span className="side__badge">{pending > 999 ? '999+' : pending}</span> : null}
                  </button>
                )
              })}
            </div>
          ))}
        </nav>

        <div className="side__foot">
          <span>
            <i className={`dot${health ? ' on' : ''}`} />
            {health ? '服务可用' : '正在连接'}
          </span>
          <span>
            语料范围 <b>{health ? `${health.domain_count} 个领域` : '—'}</b>
          </span>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="crumb">
            <span>我的研究课题</span>
            <b>/</b>
            <span>{project?.name ?? '—'}</span>
            <b>/</b>
            <strong>{labelOf(active)}</strong>
          </div>
          <button type="button" className="tag tag--plain" onClick={onAccount}>
            {account}
          </button>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  )
}
