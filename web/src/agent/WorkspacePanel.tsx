import Close from '@mui/icons-material/Close'
import { Box, CircularProgress, IconButton, Tab, Tabs, Tooltip } from '@mui/material'
import { lazy, Suspense, useState, type ReactNode } from 'react'
import type { Storage, Tree } from '../api/types'
import { Explorer } from './Explorer'
import type { OpenFiles } from './files'
import { Notes, Skills } from './Knowledge'
import { Preview } from './Preview'

// Monaco is most of the page's weight; it loads the first time the panel opens.
const Editor = lazy(() => import('./Editor').then((m) => ({ default: m.Editor })))

type Props = {
  agentId: string
  tree: Tree | null
  letters: Map<string, string>
  storage: Storage | null
  files: OpenFiles
  version: number
  view: 'editor' | 'preview'
  onView: (view: 'editor' | 'preview') => void
  onOpen: (path: string) => void
  onRefresh: () => void
  onCreate: (path: string) => void
  onClose: () => void
  /** Wide enough to put the file list beside the editor rather than above it. */
  wide: boolean
}

// No minimum tab width, so Files, Skills and Notes all fit the 220px file column.
const tabsSx = { minHeight: 36, borderBottom: 1, borderColor: 'divider', '& .MuiTab-root': { minHeight: 36, minWidth: 0, px: 1, py: 0, fontSize: 12, textTransform: 'none' } }

/** Files, skills and notes beside the chat, with the editor and the preview. */
export function WorkspacePanel({ agentId, tree, letters, storage, files, version, view, onView, onOpen, onRefresh, onCreate, onClose, wide }: Props) {
  const [tab, setTab] = useState<'files' | 'skills' | 'notes'>('files')
  const fill = (shown: boolean, children: ReactNode) => <Box sx={{ flexGrow: 1, minHeight: 0, display: shown ? 'block' : 'none' }}>{children}</Box>
  return (
    <Box component="section" aria-label="Workspace panel" sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: 'background.paper' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', borderBottom: 1, borderColor: 'divider' }}>
        <Tabs value={view} onChange={(_, v) => onView(v)} sx={{ ...tabsSx, borderBottom: 0, flexGrow: 1 }}>
          <Tab value="editor" label="Editor" />
          <Tab value="preview" label="Preview" />
        </Tabs>
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
          {tab === 'files' && <Explorer tree={tree} letters={letters} active={files.active} onOpen={onOpen} onRefresh={onRefresh} onCreate={onCreate} storage={storage} />}
          {tab === 'skills' && <Skills agentId={agentId} version={version} onOpen={onOpen} />}
          {tab === 'notes' && <Notes agentId={agentId} version={version} />}
        </Box>
        {/* Both stay mounted, so unsaved edits and a loaded preview survive switching. */}
        <Box sx={{ flexGrow: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          {fill(view === 'editor', (
            <Suspense fallback={<Box sx={{ display: 'grid', placeItems: 'center', height: '100%' }}><CircularProgress size={20} aria-label="Loading the editor" /></Box>}>
              <Editor agentId={agentId} files={files} letters={letters} />
            </Suspense>
          ))}
          {fill(view === 'preview', <Preview agentId={agentId} active={view === 'preview'} />)}
        </Box>
      </Box>
    </Box>
  )
}
