import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Processes } from '../api/types'
import type { OpenFiles } from './files'

const POLL_MS = 5000

/** The agent's processes and listening ports, polled while the panel is open and the page is
 * shown. A port that starts listening opens its preview tab, behind the current tab when one is
 * open. A preview tab the user closed stays closed until that port stops and listens again. */
export function usePorts(agentId: string, open: boolean, files: OpenFiles) {
  const [data, setData] = useState<Processes | null>(null)
  const [error, setError] = useState('')
  // Ports seen on the last poll, and ports whose tab the user closed while they listened.
  const seen = useRef<Set<number> | null>(null)
  const dismissed = useRef(new Set<number>())
  const filesRef = useRef(files)
  filesRef.current = files

  const load = useCallback(async () => {
    try {
      const next = await api<Processes>(`/api/agents/${agentId}/processes`)
      setData(next)
      setError('')
      const now = new Set(next.ports)
      for (const port of dismissed.current) if (!now.has(port)) dismissed.current.delete(port)
      const f = filesRef.current
      for (const port of next.ports) {
        if (seen.current?.has(port) || dismissed.current.has(port) || f.previews.includes(port)) continue
        f.openPreview(port, f.active === null)
      }
      seen.current = now
    } catch (e) {
      setError(errorText(e))
    }
  }, [agentId])

  useEffect(() => {
    if (!open) return
    const tick = () => document.visibilityState === 'visible' && load()
    tick()
    const timer = setInterval(tick, POLL_MS)
    document.addEventListener('visibilitychange', tick)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [open, load])

  const dismiss = useCallback((port: number) => {
    if (data?.ports.includes(port)) dismissed.current.add(port)
    filesRef.current.closePreview(port)
  }, [data])

  return { data, error, clearError: () => setError(''), load, dismiss }
}

export type Ports = ReturnType<typeof usePorts>
