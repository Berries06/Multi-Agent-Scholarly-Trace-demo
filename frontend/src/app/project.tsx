/**
 * 当前课题的上下文。
 *
 * 全站每页都挂在"我的某个研究课题"下面：课题名显示在顶栏，所有读写都带 project_id。
 * 选中的课题存在 localStorage，换页不丢；换账号时课题列表本身来自服务端，不会串。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { createProject, getProjects } from '../api'
import type { Project } from '../types'

interface ProjectState {
  projects: Project[]
  active: Project | null
  loading: boolean
  error: string | null
  select: (projectId: string) => void
  refresh: () => Promise<void>
  create: (name: string, description?: string) => Promise<Project | null>
}

const STORAGE_KEY = 'yanhai.activeProject'

const ProjectContext = createContext<ProjectState | null>(null)

export function ProjectProvider({ children, enabled }: { children: ReactNode; enabled: boolean }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [activeId, setActiveId] = useState<string>(() => {
    if (typeof window === 'undefined') return ''
    return window.localStorage.getItem(STORAGE_KEY) ?? ''
  })
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!enabled) return
    setLoading(true)
    try {
      const result = await getProjects()
      setProjects(result.projects ?? [])
      setError(null)
    } catch (err) {
      setProjects([])
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [enabled])

  useEffect(() => {
    void load()
  }, [load])

  // 选中的课题不存在了（被删、换了账号），退回第一个
  const active = useMemo(() => {
    const found = projects.find((item) => item.project_id === activeId)
    return found ?? projects[0] ?? null
  }, [projects, activeId])

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (active) window.localStorage.setItem(STORAGE_KEY, active.project_id)
  }, [active])

  const select = useCallback((projectId: string) => setActiveId(projectId), [])

  const create = useCallback(
    async (name: string, description?: string) => {
      try {
        const project = await createProject({ name, description })
        setProjects((current) => [project, ...current])
        setActiveId(project.project_id)
        return project
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
        return null
      }
    },
    [],
  )

  const value: ProjectState = {
    projects,
    active,
    loading,
    error,
    select,
    refresh: load,
    create,
  }

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

export function useProject(): ProjectState {
  const value = useContext(ProjectContext)
  if (!value) throw new Error('useProject 必须在 ProjectProvider 里使用')
  return value
}
