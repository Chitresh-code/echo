import { Alert, Box, Button, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { ProcessLog } from '../api/types'
import { MONO } from '../theme'
import type { Ports } from './ports'

const LOG_POLL_MS = 3000

type Props = { agentId: string; ports: Ports; onShow: (port: number) => void }

/** The agent's background processes, their output, and the ports they listen on. */
export function Processes({ agentId, ports, onShow }: Props) {
  const [logsOf, setLogsOf] = useState<string | null>(null)
  const [log, setLog] = useState('')
  const [error, setError] = useState('')

  // A process's output follows along while it is shown.
  useEffect(() => {
    if (!logsOf) return
    let gone = false
    const read = () =>
      api<ProcessLog>(`/api/agents/${agentId}/processes/${encodeURIComponent(logsOf)}/logs`)
        .then((r) => !gone && setLog(r.log))
        .catch((e) => !gone && setError(errorText(e)))
    read()
    const timer = setInterval(read, LOG_POLL_MS)
    return () => {
      gone = true
      clearInterval(timer)
    }
  }, [agentId, logsOf])

  async function stop(name: string) {
    try {
      await api(`/api/agents/${agentId}/processes/${encodeURIComponent(name)}`, { method: 'DELETE' })
      await ports.load()
    } catch (e) {
      setError(errorText(e))
    }
  }

  const processes = ports.data?.processes ?? []
  const listening = ports.data?.ports ?? []
  const shown = error || ports.error
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {shown && <Alert severity="error" onClose={() => (setError(''), ports.clearError())} sx={{ borderRadius: 0, py: 0 }}>{shown}</Alert>}
      <Box sx={{ overflow: 'auto', flexShrink: 0, maxHeight: logsOf ? '45%' : '100%' }}>
        {ports.data && processes.length === 0 && listening.length === 0 && (
          <Typography color="text.secondary" sx={{ px: 2, py: 1.5, fontSize: 13 }}>
            Nothing is running. Ask the agent to start a dev server, and its page opens in a tab beside your files.
          </Typography>
        )}
        {listening.length > 0 && (
          <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1, px: 2, py: 1 }}>
            <Typography color="text.secondary" sx={{ fontSize: 12 }}>Listening</Typography>
            {listening.map((p) => (
              <Button key={p} size="small" variant="outlined" onClick={() => onShow(p)} sx={{ fontFamily: MONO, minWidth: 0 }}>{p}</Button>
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
              <Button size="small" aria-pressed={logsOf === p.name} onClick={() => { setLog(''); setLogsOf(logsOf === p.name ? null : p.name) }}>Output</Button>
              {p.status === 'running' && <Button size="small" color="error" onClick={() => stop(p.name)}>Stop</Button>}
            </Box>
          ))}
        </Box>
      </Box>
      {logsOf && (
        <Box component="pre" aria-label={`Output of ${logsOf}`} sx={{ flexGrow: 1, minHeight: 0, overflow: 'auto', m: 0, px: 2, py: 1, borderTop: 1, borderColor: 'divider', fontFamily: MONO, fontSize: 12, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {log || 'No output yet.'}
        </Box>
      )}
    </Box>
  )
}
