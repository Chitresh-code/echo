import Close from '@mui/icons-material/Close'
import OpenInNew from '@mui/icons-material/OpenInNew'
import Refresh from '@mui/icons-material/Refresh'
import { Alert, Box, Button, IconButton, Tooltip, Typography } from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { api, ApiError, errorText } from '../api/client'
import type { ProcessLog, Processes } from '../api/types'
import { MONO } from '../theme'

const POLL_MS = 3000

// What fills the space under the list: a port's page, a process's output, or nothing.
type Shown = { port: number; url: string } | { logs: string } | null

/** The agent's processes and listening ports, and a frame showing one port's page. Polls only
 * while `active`, so a hidden view costs nothing; the frame stays loaded while hidden. */
export function Preview({ agentId, active }: { agentId: string; active: boolean }) {
  const [data, setData] = useState<Processes | null>(null)
  const [shown, setShown] = useState<Shown>(null)
  const [log, setLog] = useState('')
  const [off, setOff] = useState(false)
  const [error, setError] = useState('')
  const logsOf = shown && 'logs' in shown ? shown.logs : null

  const load = useCallback(async () => {
    try {
      setData(await api<Processes>(`/api/agents/${agentId}/processes`))
      if (logsOf) setLog((await api<ProcessLog>(`/api/agents/${agentId}/processes/${encodeURIComponent(logsOf)}/logs`)).log)
    } catch (e) {
      setError(errorText(e))
    }
  }, [agentId, logsOf])

  useEffect(() => {
    if (!active) return
    load()
    const timer = setInterval(load, POLL_MS)
    return () => clearInterval(timer)
  }, [active, load])

  // A fresh link every time: it works for a minute, and a new tab needs its own cookie.
  const startUrl = (port: number) => api<{ url: string }>(`/api/agents/${agentId}/preview`, { method: 'POST', body: { port } }).then((r) => r.url)

  async function show(port: number) {
    try {
      setShown({ port, url: await startUrl(port) })
    } catch (e) {
      if (e instanceof ApiError && e.code === 'preview_off') setOff(true)
      else setError(errorText(e))
    }
  }

  async function openTab(port: number) {
    // Opened before the request, so the browser counts it as the click's and does not block it.
    const tab = window.open('', '_blank')
    try {
      const url = await startUrl(port)
      if (tab) {
        tab.opener = null
        tab.location.href = url
      }
    } catch (e) {
      tab?.close()
      setError(errorText(e))
    }
  }

  async function stop(name: string) {
    try {
      await api(`/api/agents/${agentId}/processes/${encodeURIComponent(name)}`, { method: 'DELETE' })
      await load()
    } catch (e) {
      setError(errorText(e))
    }
  }

  const processes = data?.processes ?? []
  const ports = data?.ports ?? []
  return (
    <Box component="section" aria-label="Preview" sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, bgcolor: 'background.default' }}>
      {error && <Alert severity="error" onClose={() => setError('')} sx={{ borderRadius: 0 }}>{error}</Alert>}
      <Box sx={{ maxHeight: '40%', overflow: 'auto', borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper', flexShrink: 0 }}>
        {data && processes.length === 0 && ports.length === 0 && (
          <Typography color="text.secondary" sx={{ px: 2, py: 1.5, fontSize: 13 }}>
            Nothing is running. Ask the agent to start a dev server, and its port shows up here.
          </Typography>
        )}
        {ports.length > 0 && (
          <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1, px: 2, py: 1 }}>
            <Typography color="text.secondary" sx={{ fontSize: 12 }}>Listening</Typography>
            {ports.map((p) => (
              <Button key={p} size="small" variant={shown && 'port' in shown && shown.port === p ? 'contained' : 'outlined'} onClick={() => show(p)} sx={{ fontFamily: MONO, minWidth: 0 }}>
                {p}
              </Button>
            ))}
          </Box>
        )}
        <Box component="ul" aria-label="Processes" sx={{ listStyle: 'none', m: 0, p: 0 }}>
          {processes.map((p) => (
            <Box component="li" key={p.name} sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 2, py: 0.5, borderTop: 1, borderColor: 'divider' }}>
              <Box component="span" aria-hidden="true" sx={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0, bgcolor: p.status === 'running' ? 'success.main' : 'text.disabled' }} />
              <Box component="span" sx={{ fontFamily: MONO, fontSize: 13, fontWeight: 600 }}>{p.name}</Box>
              <Box component="span" title={p.command} sx={{ fontFamily: MONO, fontSize: 12, color: 'text.secondary', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexGrow: 1, minWidth: 0 }}>
                {p.command}
              </Box>
              <Typography component="span" color="text.secondary" sx={{ fontSize: 12, flexShrink: 0 }}>
                {p.status === 'running' ? 'running' : `exited ${p.exit_code ?? ''}`.trim()}
              </Typography>
              <Button size="small" onClick={() => { setLog(''); setShown({ logs: p.name }) }}>Output</Button>
              {p.status === 'running' && <Button size="small" color="error" onClick={() => stop(p.name)}>Stop</Button>}
            </Box>
          ))}
        </Box>
      </Box>
      {off && !shown && (
        <Typography color="text.secondary" sx={{ px: 2, py: 1.5, fontSize: 13 }}>
          Previews are not set up on this Echo server, so pages cannot be shown here. Whoever runs it can turn them on with ECHO_PREVIEW_URL.
        </Typography>
      )}
      {shown && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, px: 1, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper', minHeight: 36 }}>
          <Typography sx={{ fontFamily: MONO, fontSize: 12, px: 1, flexGrow: 1 }}>{'port' in shown ? `localhost:${shown.port}` : `Output of ${shown.logs}`}</Typography>
          {'port' in shown && (
            <>
              <Tooltip title="Reload"><IconButton size="small" aria-label="Reload" onClick={() => show(shown.port)}><Refresh sx={{ fontSize: 16 }} /></IconButton></Tooltip>
              <Tooltip title="Open in a new tab"><IconButton size="small" aria-label="Open in a new tab" onClick={() => openTab(shown.port)}><OpenInNew sx={{ fontSize: 16 }} /></IconButton></Tooltip>
            </>
          )}
          <Tooltip title="Close"><IconButton size="small" aria-label="Close" onClick={() => setShown(null)}><Close sx={{ fontSize: 16 }} /></IconButton></Tooltip>
        </Box>
      )}
      {shown && 'port' in shown && (
        // Its own origin, so allow-same-origin gives the page its own storage and nothing of Echo's.
        <Box component="iframe" key={shown.url} src={shown.url} title={`Preview of port ${shown.port}`}
          sandbox="allow-scripts allow-forms allow-same-origin allow-popups allow-downloads"
          sx={{ flexGrow: 1, minHeight: 0, width: '100%', border: 0, bgcolor: '#fff' }} />
      )}
      {shown && 'logs' in shown && (
        <Box component="pre" sx={{ flexGrow: 1, minHeight: 0, overflow: 'auto', m: 0, px: 2, py: 1, fontFamily: MONO, fontSize: 12, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {log || 'No output yet.'}
        </Box>
      )}
    </Box>
  )
}
