import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, errorText } from '../api/client'
import type { Agent } from '../api/types'

type Workspaces = {
  /** Most recently used first; null until the first load ends. */
  workspaces: Agent[] | null
  error: string
  reload: () => void
  /** Adds or replaces one, after the page created, renamed or used it. */
  upsert: (agent: Agent) => void
  /** Renames at once and puts the old name back if the api refuses; throws the api's error. */
  rename: (id: string, name: string) => Promise<void>
  /** Deletes on the api, then from the list; throws the api's error (such as a turn in progress). */
  remove: (id: string) => Promise<void>
}

const WorkspacesContext = createContext<Workspaces | null>(null)

export function useWorkspaces(): Workspaces {
  const value = useContext(WorkspacesContext)
  if (!value) throw new Error('useWorkspaces needs a WorkspacesProvider')
  return value
}

// The api's own order, kept when the page adds or changes one.
const recent = (a: Agent) => a.last_used_at ?? a.created_at
const sorted = (list: Agent[]) => [...list].sort((a, b) => recent(b).localeCompare(recent(a)))

/** The signed-in user's workspaces, shared by the sidebar and the pages. */
export function WorkspacesProvider({ children }: { children: ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Agent[] | null>(null)
  const [error, setError] = useState('')
  const current = useRef(workspaces)
  current.current = workspaces

  const reload = useCallback(() => {
    setError('')
    api<Agent[]>('/api/agents').then(setWorkspaces, (e) => setError(errorText(e)))
  }, [])
  useEffect(reload, [reload])

  const upsert = useCallback((agent: Agent) => {
    setWorkspaces((all) => sorted([agent, ...(all ?? []).filter((a) => a.id !== agent.id)]))
  }, [])

  const rename = useCallback(async (id: string, name: string) => {
    const before = current.current?.find((a) => a.id === id)
    setWorkspaces((all) => all?.map((a) => (a.id === id ? { ...a, name } : a)) ?? null)
    try {
      upsert(await api<Agent>(`/api/agents/${id}`, { method: 'PATCH', body: { name } }))
    } catch (e) {
      if (before) upsert(before)
      throw e
    }
  }, [upsert])

  const remove = useCallback(async (id: string) => {
    await api(`/api/agents/${id}`, { method: 'DELETE' })
    setWorkspaces((all) => all?.filter((a) => a.id !== id) ?? null)
  }, [])

  const value = useMemo(() => ({ workspaces, error, reload, upsert, rename, remove }), [workspaces, error, reload, upsert, rename, remove])
  return <WorkspacesContext.Provider value={value}>{children}</WorkspacesContext.Provider>
}
