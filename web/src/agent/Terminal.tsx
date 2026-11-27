import { useTheme } from '@mui/material'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal as XTerm } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { useEffect, useRef } from 'react'
import { MONO } from '../theme'

// Waits before each reconnect, as the chat does; the last repeats.
const RETRY_MS = [1000, 2000, 5000, 10000]

/** Why a shell's socket closed for good. */
export type Ended = 'exited' | 'gone' | 'signed_out'

type Props = {
  agentId: string
  id: string
  /** Shown now: fitted to its box and focused. Hidden ones stay connected. */
  active: boolean
  onEnded: (id: string, why: Ended) => void
}

export function socketUrl(agentId: string, id: string): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}/api/agents/${agentId}/terminals/${id}`
}

/** One shell. The shell runs on the server, so a dropped socket reconnects and the server
 * replays the recent output; the screen is reset first so nothing shows twice. */
export function Terminal({ agentId, id, active, onEnded }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const term = useRef<XTerm | null>(null)
  const fit = useRef<FitAddon | null>(null)
  const sock = useRef<WebSocket | null>(null)
  const ended = useRef(onEnded)
  ended.current = onEnded
  const theme = useTheme()

  const sendSize = () => {
    const t = term.current
    if (t && sock.current?.readyState === WebSocket.OPEN) sock.current.send(JSON.stringify({ type: 'resize', cols: t.cols, rows: t.rows }))
  }

  useEffect(() => {
    const t = new XTerm({ fontFamily: MONO, fontSize: 13, cursorBlink: true, scrollback: 5000, allowProposedApi: false })
    const f = new FitAddon()
    t.loadAddon(f)
    t.open(box.current!)
    term.current = t
    fit.current = f
    let attempt = 0
    let timer: number | undefined
    let stopped = false

    const connect = () => {
      const ws = new WebSocket(socketUrl(agentId, id))
      ws.binaryType = 'arraybuffer'
      sock.current = ws
      ws.onopen = () => {
        attempt = 0
        t.reset()
        sendSize()
      }
      ws.onmessage = (e) => t.write(new Uint8Array(e.data as ArrayBuffer))
      ws.onclose = (e) => {
        if (stopped) return
        if (e.code === 1000) {
          t.write('\r\n\x1b[2mThe shell has exited.\x1b[0m\r\n')
          ended.current(id, 'exited')
        } else if (e.code === 4404) {
          ended.current(id, 'gone')
        } else if (e.code === 4401) {
          t.write('\r\n\x1b[2mYou are signed out. Sign in again to use this terminal.\x1b[0m\r\n')
          ended.current(id, 'signed_out')
        } else {
          const wait = RETRY_MS[Math.min(attempt++, RETRY_MS.length - 1)]
          t.write(`\r\n\x1b[2mConnection lost. Reconnecting in ${wait / 1000} s…\x1b[0m\r\n`)
          timer = window.setTimeout(connect, wait)
        }
      }
    }

    const input = t.onData((data) => {
      if (sock.current?.readyState === WebSocket.OPEN) sock.current.send(JSON.stringify({ type: 'input', data }))
    })
    const resized = t.onResize(sendSize)
    // Fitting a hidden box measures zero, so only a shown terminal follows its box.
    const observer = new ResizeObserver(() => {
      if (box.current?.offsetParent) f.fit()
    })
    observer.observe(box.current!)
    connect()
    return () => {
      stopped = true
      window.clearTimeout(timer)
      observer.disconnect()
      input.dispose()
      resized.dispose()
      sock.current?.close()
      t.dispose()
    }
  }, [agentId, id])

  useEffect(() => {
    if (!term.current) return
    term.current.options.theme = {
      background: theme.palette.background.default,
      foreground: theme.palette.text.primary,
      cursor: theme.palette.primary.main,
      selectionBackground: theme.palette.action.selected,
    }
  }, [theme])

  useEffect(() => {
    if (!active) return
    fit.current?.fit()
    term.current?.focus()
  }, [active])

  return <div ref={box} role="group" aria-label="Terminal" style={{ height: '100%', width: '100%', padding: '4px 0 0 8px', boxSizing: 'border-box', display: active ? 'block' : 'none' }} />
}
