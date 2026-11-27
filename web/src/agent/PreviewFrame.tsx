import Fullscreen from '@mui/icons-material/Fullscreen'
import FullscreenExit from '@mui/icons-material/FullscreenExit'
import OpenInNew from '@mui/icons-material/OpenInNew'
import Refresh from '@mui/icons-material/Refresh'
import { Alert, Box, CircularProgress, IconButton, Tooltip, Typography } from '@mui/material'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, errorText } from '../api/client'
import { MONO } from '../theme'

type Props = { agentId: string; port: number; listening: boolean; shown: boolean }

/** One port's page, in a tab like a file. It stays loaded while another tab is shown. */
export function PreviewFrame({ agentId, port, listening, shown }: Props) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  const [off, setOff] = useState(false)
  const [full, setFull] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  // A fresh link every time: it works for a minute, and each load needs its own cookie.
  const startUrl = useCallback(() => api<{ url: string }>(`/api/agents/${agentId}/preview`, { method: 'POST', body: { port } }).then((r) => r.url), [agentId, port])

  const load = useCallback(async () => {
    setError('')
    try {
      setUrl(await startUrl())
    } catch (e) {
      if (e instanceof ApiError && e.code === 'preview_off') setOff(true)
      else setError(errorText(e))
    }
  }, [startUrl])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const change = () => setFull(document.fullscreenElement === box.current)
    document.addEventListener('fullscreenchange', change)
    return () => document.removeEventListener('fullscreenchange', change)
  }, [])

  async function openTab() {
    // Opened before the request, so the browser counts it as the click's and does not block it.
    const tab = window.open('', '_blank')
    try {
      const next = await startUrl()
      if (tab) {
        tab.opener = null
        tab.location.href = next
      }
    } catch (e) {
      tab?.close()
      setError(errorText(e))
    }
  }

  function toggleFull() {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
    else box.current?.requestFullscreen().catch(() => setError('This browser did not allow full screen. Open the page in a new tab instead.'))
  }

  const icon = { fontSize: 16 }
  return (
    <Box ref={box} component="section" aria-label={`Preview of port ${port}`} sx={{ display: shown || full ? 'flex' : 'none', flexDirection: 'column', flexGrow: 1, minHeight: 0, bgcolor: 'background.default' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, px: 1, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper', minHeight: 36 }}>
        <Typography sx={{ fontFamily: MONO, fontSize: 12, px: 1, flexGrow: 1 }}>localhost:{port}</Typography>
        <Tooltip title="Reload"><IconButton size="small" aria-label="Reload" onClick={load} disabled={off}><Refresh sx={icon} /></IconButton></Tooltip>
        <Tooltip title="Open in a new tab"><IconButton size="small" aria-label="Open in a new tab" onClick={openTab} disabled={off}><OpenInNew sx={icon} /></IconButton></Tooltip>
        <Tooltip title={full ? 'Exit full screen' : 'Full screen'}>
          <IconButton size="small" aria-label={full ? 'Exit full screen' : 'Full screen'} onClick={toggleFull} disabled={off}>{full ? <FullscreenExit sx={icon} /> : <Fullscreen sx={icon} />}</IconButton>
        </Tooltip>
      </Box>
      {!listening && <Alert severity="info" sx={{ borderRadius: 0, py: 0 }}>Nothing is listening on port {port} now. The page shows its last state until the server starts again.</Alert>}
      {error && <Alert severity="error" onClose={() => setError('')} sx={{ borderRadius: 0, py: 0 }}>{error}</Alert>}
      {off ? (
        <Typography color="text.secondary" sx={{ px: 2, py: 1.5, fontSize: 13 }}>
          Previews are not set up on this Echo server, so pages cannot be shown here. Whoever runs it can turn them on with ECHO_PREVIEW_URL.
        </Typography>
      ) : url ? (
        // Its own origin, so allow-same-origin gives the page its own storage and nothing of Echo's.
        <Box component="iframe" key={url} src={url} title={`Preview of port ${port}`}
          sandbox="allow-scripts allow-forms allow-same-origin allow-popups allow-downloads"
          sx={{ flexGrow: 1, minHeight: 0, width: '100%', border: 0, bgcolor: '#fff' }} />
      ) : (
        !error && <Box sx={{ display: 'grid', placeItems: 'center', flexGrow: 1 }}><CircularProgress size={20} aria-label="Loading the preview" /></Box>
      )}
    </Box>
  )
}
