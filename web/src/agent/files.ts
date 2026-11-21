import { useCallback, useRef, useState } from 'react'
import { api, ApiError, errorText } from '../api/client'
import type { AgentFile, GitFileVersions } from '../api/types'

export type OpenFile = {
  path: string
  loading: boolean
  error: string
  binary: boolean
  // What is on disk as of the last read or save; `value` differs from it while there are unsaved edits.
  saved: string
  value: string
  changedOnDisk: boolean
  mode: 'edit' | 'diff'
  // The last committed version, for the diff; null for a file not in the last commit.
  head: string | null
}

const blank = (path: string, mode: OpenFile['mode']): OpenFile => ({
  path, loading: true, error: '', binary: false, saved: '', value: '', changedOnDisk: false, mode, head: null,
})

async function readHead(agentId: string, path: string): Promise<string | null> {
  const v = await api<GitFileVersions>(`/api/agents/${agentId}/git/file?path=${encodeURIComponent(path)}`)
  return v.head?.encoding === 'utf-8' ? v.head.content : null
}

/** The files open in the editor's tabs, and keeping them in step with the agent's workspace. */
export function useOpenFiles(agentId: string) {
  const [files, setFiles] = useState<OpenFile[]>([])
  const [active, setActive] = useState<string | null>(null)
  const filesRef = useRef(files)
  filesRef.current = files

  const update = useCallback((path: string, change: Partial<OpenFile>) => {
    setFiles((all) => all.map((f) => (f.path === path ? { ...f, ...change } : f)))
  }, [])

  const load = useCallback(
    async (path: string, withHead: boolean) => {
      try {
        const file = await api<AgentFile>(`/api/agents/${agentId}/file?path=${encodeURIComponent(path)}`)
        const binary = file.encoding === 'base64'
        const content = binary ? '' : file.content
        const head = withHead && !binary ? await readHead(agentId, path) : null
        return { loading: false, error: '', binary, content, head }
      } catch (e) {
        const gone = e instanceof ApiError && e.code === 'file_not_found'
        return { loading: false, error: gone ? 'This file is no longer in the workspace.' : errorText(e), binary: false, content: '', head: null }
      }
    },
    [agentId],
  )

  const open = useCallback(
    async (path: string, changed: boolean) => {
      setActive(path)
      if (filesRef.current.some((f) => f.path === path)) return
      // A changed file opens on its diff, since what changed is usually why it is opened.
      setFiles((all) => [...all, blank(path, changed ? 'diff' : 'edit')])
      const { content, ...rest } = await load(path, changed)
      update(path, { ...rest, saved: content, value: content })
    },
    [load, update],
  )

  const close = useCallback((path: string) => {
    setFiles((all) => {
      const next = all.filter((f) => f.path !== path)
      setActive((current) => (current === path ? (next.at(-1)?.path ?? null) : current))
      return next
    })
  }, [])

  const setMode = useCallback(
    async (path: string, mode: OpenFile['mode']) => {
      update(path, { mode })
      if (mode === 'diff') update(path, { head: await readHead(agentId, path).catch(() => null) })
    },
    [agentId, update],
  )

  const save = useCallback(
    async (path: string) => {
      const file = filesRef.current.find((f) => f.path === path)
      if (!file || file.binary) return
      const value = file.value
      try {
        await api(`/api/agents/${agentId}/file`, { method: 'PUT', body: { path, content: value } })
        update(path, { saved: value, changedOnDisk: false, error: '' })
      } catch (e) {
        update(path, { error: errorText(e) })
      }
    },
    [agentId, update],
  )

  /** Re-reads every open file after the agent may have changed them. Unsaved edits are never
   *  replaced; such a file is marked "Changed on disk" instead. */
  const refresh = useCallback(async () => {
    await Promise.all(
      filesRef.current.map(async (f) => {
        const { content, ...rest } = await load(f.path, f.mode === 'diff')
        setFiles((all) =>
          all.map((cur) => {
            if (cur.path !== f.path) return cur
            const dirty = cur.value !== cur.saved
            if (!dirty) return { ...cur, ...rest, saved: content, value: content, changedOnDisk: false }
            return { ...cur, head: rest.head, changedOnDisk: !rest.error && content !== cur.saved }
          }),
        )
      }),
    )
  }, [load])

  const reload = useCallback(
    async (path: string) => {
      const { content, ...rest } = await load(path, filesRef.current.find((f) => f.path === path)?.mode === 'diff')
      update(path, { ...rest, saved: content, value: content, changedOnDisk: false })
    },
    [load, update],
  )

  return { files, active, setActive, open, close, update, setMode, save, refresh, reload }
}

export type OpenFiles = ReturnType<typeof useOpenFiles>
