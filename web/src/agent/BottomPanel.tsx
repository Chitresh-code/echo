import Add from '@mui/icons-material/Add'
import Close from '@mui/icons-material/Close'
import { Alert, Box, CircularProgress, IconButton, Tooltip, Typography } from '@mui/material'
import { lazy, Suspense, useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { api, errorText } from '../api/client'
import { read, write } from '../storage'
import type { Ended } from './Terminal'

// xterm loads the first time the panel opens, as Monaco does with the editor.
const Terminal = lazy(() => import('./Terminal').then((m) => ({ default: m.Terminal })))

const HEIGHT = 'echo.terminal.height'
const MIN_HEIGHT = 120
const DEFAULT_HEIGHT = 260
// Leaves the editor at least this much of the panel.
const EDITOR_MIN = 160

type Shell = { id: string; started_at: number }
type Props = {
  agentId: string
  open: boolean
  onClose: () => void
  /** Extra tabs after the shells (Processes), as [key, label, body]. */
  extra?: { key: string; label: string; body: ReactNode }[]
}

const clamp = (h: number, room: number) => Math.round(Math.max(MIN_HEIGHT, Math.min(h, room - EDITOR_MIN)))

/** Shells under the editor, as VS Code's panel. Shells live on the server, so the list comes from
 * it each time the panel opens: a reload or a second tab finds the same ones. */
export function BottomPanel({ agentId, open, onClose, extra = [] }: Props) {
  const [shells, setShells] = useState<Shell[] | null>(null)
  const [tab, setTab] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [height, setHeight] = useState(() => Number(read(HEIGHT)) || DEFAULT_HEIGHT)
  const root = useRef<HTMLDivElement>(null)

  const start = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      const shell = await api<Shell>(`/api/agents/${agentId}/terminals`, { method: 'POST', body: { cols: 80, rows: 24 } })
      setShells((s) => [...(s ?? []), shell])
      setTab(shell.id)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }, [agentId])

  // On each open: find the shells already running, or start one if there are none.
  useEffect(() => {
    if (!open) return
    let gone = false
    api<{ terminals: Shell[] }>(`/api/agents/${agentId}/terminals`)
      .then(({ terminals }) => {
        if (gone) return
        setShells(terminals)
        setTab((t) => (t && (terminals.some((s) => s.id === t) || extra.some((x) => x.key === t)) ? t : terminals[0]?.id ?? null))
        if (terminals.length === 0) start()
      })
      .catch((e) => !gone && setError(errorText(e)))
    return () => {
      gone = true
    }
  }, [open, agentId])

  const drop = useCallback((id: string) => {
    setShells((s) => {
      const left = (s ?? []).filter((x) => x.id !== id)
      setTab((t) => (t === id ? left.at(-1)?.id ?? extra[0]?.key ?? null : t))
      return left
    })
  }, [extra])

  const ended = useCallback((id: string, why: Ended) => {
    // An exited shell keeps its last screen until its tab is closed; a missing one just goes.
    if (why === 'gone') drop(id)
    if (why === 'signed_out') setError('You are signed out. Sign in again to use the terminal.')
  }, [drop])

  async function close(id: string) {
    drop(id)
    try {
      await api(`/api/agents/${agentId}/terminals/${id}`, { method: 'DELETE' })
    } catch {
      // Already ended on the server: nothing left to close.
    }
  }

  function resize(e: PointerEvent<HTMLElement>) {
    const startY = e.clientY
    const start = height
    const room = root.current?.parentElement?.clientHeight ?? window.innerHeight
    const handle = e.currentTarget
    handle.setPointerCapture(e.pointerId)
    let last = start
    const move = (ev: globalThis.PointerEvent) => setHeight((last = clamp(start + startY - ev.clientY, room)))
    const up = () => {
      handle.removeEventListener('pointermove', move)
      handle.removeEventListener('pointerup', up)
      write(HEIGHT, String(last))
    }
    handle.addEventListener('pointermove', move)
    handle.addEventListener('pointerup', up)
  }

  function resizeByKey(e: KeyboardEvent<HTMLElement>) {
    const step = e.key === 'ArrowUp' ? 32 : e.key === 'ArrowDown' ? -32 : 0
    if (!step) return
    e.preventDefault()
    const next = clamp(height + step, root.current?.parentElement?.clientHeight ?? window.innerHeight)
    setHeight(next)
    write(HEIGHT, String(next))
  }

  const full = (shells?.length ?? 0) >= 4
  const tabSx = (on: boolean) => ({
    display: 'flex', alignItems: 'center', gap: 0.25, pl: 1.25, pr: 0.25, height: 32, cursor: 'pointer', fontSize: 12, whiteSpace: 'nowrap',
    color: on ? 'text.primary' : 'text.secondary', borderBottom: 2, borderColor: on ? 'primary.main' : 'transparent',
    '&:hover': { color: 'text.primary' }, '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: -2 },
  })
  return (
    <Box ref={root} component="section" aria-label="Terminal panel" sx={{ display: open ? 'flex' : 'none', flexDirection: 'column', height, flexShrink: 0, borderTop: 1, borderColor: 'divider', bgcolor: 'background.default', position: 'relative' }}>
      <Box role="separator" aria-orientation="horizontal" aria-label="Resize the terminal panel" aria-valuemin={MIN_HEIGHT} aria-valuenow={height} tabIndex={0}
        onPointerDown={resize} onKeyDown={resizeByKey}
        sx={{ position: 'absolute', top: -3, left: 0, right: 0, height: 6, cursor: 'row-resize', zIndex: 1, '&:hover, &:focus-visible': { bgcolor: 'primary.main', outline: 'none' } }} />
      <Box role="tablist" aria-label="Terminals" sx={{ display: 'flex', alignItems: 'center', borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper', overflowX: 'auto', flexShrink: 0 }}>
        {(shells ?? []).map((s, i) => (
          <Box key={s.id} role="tab" tabIndex={0} aria-selected={tab === s.id} onClick={() => setTab(s.id)}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), setTab(s.id))} sx={tabSx(tab === s.id)}>
            Terminal {i + 1}
            <IconButton size="small" aria-label={`Close terminal ${i + 1}`} onClick={(e) => (e.stopPropagation(), close(s.id))} sx={{ p: 0.25 }}>
              <Close sx={{ fontSize: 14 }} />
            </IconButton>
          </Box>
        ))}
        <Tooltip title={full ? 'A workspace can have 4 terminals open. Close one first.' : 'New terminal'}>
          <span>
            <IconButton size="small" aria-label="New terminal" disabled={busy || full} onClick={start} sx={{ mx: 0.5 }}>
              {busy ? <CircularProgress size={14} /> : <Add sx={{ fontSize: 16 }} />}
            </IconButton>
          </span>
        </Tooltip>
        {extra.map((x) => (
          <Box key={x.key} role="tab" tabIndex={0} aria-selected={tab === x.key} onClick={() => setTab(x.key)}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), setTab(x.key))} sx={{ ...tabSx(tab === x.key), pr: 1.25 }}>
            {x.label}
          </Box>
        ))}
        <Box sx={{ flexGrow: 1 }} />
        <Tooltip title="Hide the terminal (Ctrl+`)">
          <IconButton size="small" aria-label="Hide the terminal" onClick={onClose} sx={{ mr: 0.5 }}>
            <Close sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>
      </Box>
      {error && <Alert severity="error" onClose={() => setError('')} sx={{ borderRadius: 0, py: 0 }}>{error}</Alert>}
      <Box role="tabpanel" sx={{ flexGrow: 1, minHeight: 0 }}>
        {shells === null && !error && <Box sx={{ display: 'grid', placeItems: 'center', height: '100%' }}><CircularProgress size={18} aria-label="Loading terminals" /></Box>}
        {shells?.length === 0 && !busy && !extra.some((x) => x.key === tab) && (
          <Typography color="text.secondary" sx={{ px: 2, py: 1.5, fontSize: 13 }}>No terminal is open. Use + to open one.</Typography>
        )}
        <Suspense fallback={<Box sx={{ display: 'grid', placeItems: 'center', height: '100%' }}><CircularProgress size={18} aria-label="Loading the terminal" /></Box>}>
          {(shells ?? []).map((s) => (
            <Terminal key={s.id} agentId={agentId} id={s.id} active={open && tab === s.id} onEnded={ended} />
          ))}
        </Suspense>
        {extra.map((x) => (
          <Box key={x.key} sx={{ height: '100%', display: tab === x.key ? 'block' : 'none' }}>{x.body}</Box>
        ))}
      </Box>
    </Box>
  )
}
