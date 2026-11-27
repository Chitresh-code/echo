import Close from '@mui/icons-material/Close'
import TerminalIcon from '@mui/icons-material/Terminal'
import { Box, CircularProgress, IconButton, Tab, Tabs, Tooltip, Typography } from '@mui/material'
import { lazy, Suspense, useEffect, useState } from 'react'
import type { Storage, Tree } from '../api/types'
import { BottomPanel } from './BottomPanel'
import { Explorer, type NewKind } from './Explorer'
import type { OpenFiles } from './files'
import { Notes, Skills } from './Knowledge'
import { usePorts } from './ports'
import { Processes } from './Processes'

// Monaco is most of the page's weight; it loads the first time the panel opens.
const Editor = lazy(() => import('./Editor').then((m) => ({ default: m.Editor })))

type Props = {
  agentId: string
  tree: Tree | null
  letters: Map<string, string>
  storage: Storage | null
  files: OpenFiles
  version: number
  /** The panel is shown, so polling for ports is worth doing. */
  open: boolean
  onOpen: (path: string) => void
  onRefresh: () => void
  onCreate: (kind: NewKind, path: string) => Promise<void>
  onClose: () => void
  /** Wide enough to put the file list beside the editor rather than above it. */
  wide: boolean
}

// No minimum tab width, so Files, Skills and Notes all fit the 220px file column.
const tabsSx = { minHeight: 36, borderBottom: 1, borderColor: 'divider', '& .MuiTab-root': { minHeight: 36, minWidth: 0, px: 1, py: 0, fontSize: 12, textTransform: 'none' } }

/** Files, skills and notes beside the chat, with the editor and the preview. */
export function WorkspacePanel({ agentId, tree, letters, storage, files, version, open, onOpen, onRefresh, onCreate, onClose, wide }: Props) {
  const [tab, setTab] = useState<'files' | 'skills' | 'notes'>('files')
  const [terminal, setTerminal] = useState(false)
  const ports = usePorts(agentId, open, files)
  // Ctrl+` as in VS Code. Capture phase, so it works while a terminal or the editor has focus.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.ctrlKey && !e.altKey && !e.metaKey && e.code === 'Backquote') {
        e.preventDefault()
        e.stopPropagation()
        setTerminal((t) => !t)
      }
    }
    window.addEventListener('keydown', key, true)
    return () => window.removeEventListener('keydown', key, true)
  }, [])
  return (
    <Box component="section" aria-label="Workspace panel" sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: 'background.paper' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
        <Typography component="h2" sx={{ fontSize: 12, fontWeight: 600, color: 'text.secondary', px: 1.5, flexGrow: 1 }}>Workspace</Typography>
        <Tooltip title="Terminal (Ctrl+`)">
          <IconButton aria-label="Terminal" aria-pressed={terminal} onClick={() => setTerminal((t) => !t)} sx={{ width: 32, height: 32, ...(terminal && { color: 'primary.main' }) }}>
            <TerminalIcon sx={{ fontSize: 18 }} />
          </IconButton>
        </Tooltip>
        <Tooltip title="Close panel">
          <IconButton aria-label="Close panel" onClick={onClose} sx={{ width: 32, height: 32, mr: 0.5 }}>
            <Close sx={{ fontSize: 18 }} />
          </IconButton>
        </Tooltip>
      </Box>
      <Box sx={{ flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: wide ? 'row' : 'column' }}>
        <Box sx={{ width: wide ? 220 : 'auto', height: wide ? 'auto' : 220, flexShrink: 0, borderRight: wide ? 1 : 0, borderBottom: wide ? 0 : 1, borderColor: 'divider', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <Tabs value={tab} onChange={(_, t) => setTab(t)} variant="fullWidth" sx={tabsSx}>
            <Tab value="files" label="Files" />
            <Tab value="skills" label="Skills" />
            <Tab value="notes" label="Notes" />
          </Tabs>
          {tab === 'files' && <Explorer agentId={agentId} tree={tree} letters={letters} active={files.active} onOpen={onOpen} onRefresh={onRefresh} onCreate={onCreate} storage={storage} />}
          {tab === 'skills' && <Skills agentId={agentId} version={version} onOpen={onOpen} />}
          {tab === 'notes' && <Notes agentId={agentId} version={version} />}
        </Box>
        <Box sx={{ flexGrow: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          <Box sx={{ flexGrow: 1, minHeight: 0 }}>
            <Suspense fallback={<Box sx={{ display: 'grid', placeItems: 'center', height: '100%' }}><CircularProgress size={20} aria-label="Loading the editor" /></Box>}>
              <Editor agentId={agentId} files={files} letters={letters} listening={ports.data?.ports ?? []} onClosePreview={ports.dismiss} />
            </Suspense>
          </Box>
          <BottomPanel agentId={agentId} open={terminal} onClose={() => setTerminal(false)}
            extra={[{ key: 'processes', label: 'Processes', body: <Processes agentId={agentId} ports={ports} onShow={(p) => files.openPreview(p)} /> }]} />
        </Box>
      </Box>
    </Box>
  )
}
