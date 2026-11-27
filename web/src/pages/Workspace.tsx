import MoreHoriz from '@mui/icons-material/MoreHoriz'
import PostAdd from '@mui/icons-material/PostAdd'
import ViewSidebarOutlined from '@mui/icons-material/ViewSidebarOutlined'
import {
  Alert, Box, Button, ButtonBase, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Link, Menu, MenuItem, Tooltip, Typography, useMediaQuery,
} from '@mui/material'
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { Link as RouterLink, useLocation, useNavigate, useParams } from 'react-router'
import { api, ApiError, errorText } from '../api/client'
import type { Agent, GitFileStatus, Storage, Tree } from '../api/types'
import { Chat, storeChat } from '../agent/Chat'
import { useOpenFiles } from '../agent/files'
import { statusLetters } from '../agent/tree'
import { useLeaveGuard } from '../agent/useLeaveGuard'
import { WorkspacePanel } from '../agent/WorkspacePanel'
import { DeleteDialog, NameInput } from '../layout/WorkspaceActions'
import { useWorkspaces } from '../layout/workspaces'
import { MONO } from '../theme'
import { AgentDialog } from './AgentDialog'
import type { Handover } from './Home'

const PANEL = 'echo.panel'
const PANEL_WIDTH = 'echo.panel.width'
// The panel is never narrower than a usable editor, nor wider than leaves the chat readable.
const MIN_WIDTH = 320
const MAX_SHARE = 0.6
const DEFAULT_WIDTH = 640

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Storage refused: the panel keeps its state until reload.
  }
}

const clampWidth = (w: number) => Math.round(Math.max(MIN_WIDTH, Math.min(w, window.innerWidth * MAX_SHARE)))

export default function Workspace() {
  const { agentId = '' } = useParams()
  // A new workspace id means a new page: every panel starts fresh.
  return <WorkspacePage key={agentId} agentId={agentId} />
}

function WorkspacePage({ agentId }: { agentId: string }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { workspaces, upsert } = useWorkspaces()
  const wideScreen = useMediaQuery('(min-width:900px)', { noSsr: true })

  // The message typed on home: taken once and dropped from the history entry, so a reload or
  // going back and forth never sends it again.
  const [initial] = useState(() => (location.state as Handover | null)?.send)
  const arrived = useRef(false)
  useEffect(() => {
    if (arrived.current) return
    arrived.current = true
    if (initial) navigate(location.pathname, { replace: true, state: null })
  }, [initial, location.pathname, navigate])

  const [agent, setAgent] = useState<Agent | null>(null)
  const [missing, setMissing] = useState(false)
  const [tree, setTree] = useState<Tree | null>(null)
  const [statuses, setStatuses] = useState<GitFileStatus[]>([])
  const [storage, setStorage] = useState<Storage | null>(null)
  const [error, setError] = useState('')
  const [view, setView] = useState<'editor' | 'preview'>('editor')
  const [version, setVersion] = useState(0)
  const [chatEpoch, setChatEpoch] = useState(0)
  const [stop, setStop] = useState<(() => void) | null>(null)
  const [renaming, setRenaming] = useState(false)
  const [menu, setMenu] = useState<HTMLElement | null>(null)
  const [dialog, setDialog] = useState<'purpose' | 'delete' | null>(null)
  const [panelOpen, setPanelOpen] = useState(() => read(PANEL) === 'open')
  // Mounted the first time it opens and kept after, so unsaved edits survive closing it.
  const [panelMounted, setPanelMounted] = useState(panelOpen)
  const [width, setWidth] = useState(() => clampWidth(Number(read(PANEL_WIDTH)) || DEFAULT_WIDTH))
  const files = useOpenFiles(agentId)
  const letters = useMemo(() => statusLetters(statuses), [statuses])
  const guard = useLeaveGuard(stop)

  // The sidebar's copy is the live one: a rename there shows here at once.
  const live = workspaces?.find((a) => a.id === agentId) ?? agent
  const liveRef = useRef(live)
  liveRef.current = live

  useEffect(() => {
    if (!live) return
    document.title = `${live.name} · Echo`
    return () => {
      document.title = 'Echo'
    }
  }, [live])

  const refreshTree = useCallback(async () => {
    try {
      const [t, s] = await Promise.all([
        api<Tree>(`/api/agents/${agentId}/tree`),
        api<GitFileStatus[]>(`/api/agents/${agentId}/git/status`),
      ])
      setTree(t)
      setStatuses(s)
      setError('')
    } catch (e) {
      setError(errorText(e))
    }
    // Only a hint, so a failure leaves the line out instead of showing an error.
    api<Storage>(`/api/agents/${agentId}/usage`).then(setStorage, () => setStorage(null))
  }, [agentId])

  useEffect(() => {
    api<Agent>(`/api/agents/${agentId}`).then(
      (a) => {
        setAgent(a)
        refreshTree()
      },
      (e) => (e instanceof ApiError && e.status === 404 ? setMissing(true) : setError(errorText(e))),
    )
  }, [agentId, refreshTree])

  const { refresh } = files
  const afterTurn = useCallback(() => {
    refreshTree()
    refresh()
    setVersion((v) => v + 1)
  }, [refreshTree, refresh])

  // The api names a new workspace and marks it used when a turn starts: the sidebar catches up.
  const turnStarted = useCallback(() => {
    api<Agent>(`/api/agents/${agentId}`).then((a) => (setAgent(a), upsert(a)), () => {})
  }, [agentId, upsert])

  const titled = useCallback((name: string) => {
    const current = liveRef.current
    if (current) upsert({ ...current, name })
  }, [upsert])

  const running = useCallback((s: (() => void) | null) => setStop(() => s), [])

  function showPanel(open: boolean) {
    setPanelOpen(open)
    if (open) setPanelMounted(true)
    write(PANEL, open ? 'open' : 'closed')
  }

  const openFile = (path: string) => {
    setView('editor')
    showPanel(true)
    files.open(path, letters.has(path))
  }

  async function create(path: string) {
    try {
      await api(`/api/agents/${agentId}/file`, { method: 'PUT', body: { path, content: '' } })
      await refreshTree()
      files.open(path, false)
    } catch (e) {
      setError(errorText(e))
    }
  }

  function newChat() {
    storeChat(agentId, null)
    setChatEpoch((n) => n + 1)
  }

  function resize(e: PointerEvent<HTMLElement>) {
    const startX = e.clientX
    const startWidth = width
    const handle = e.currentTarget
    handle.setPointerCapture(e.pointerId)
    let last = startWidth
    const move = (ev: globalThis.PointerEvent) => setWidth((last = clampWidth(startWidth + startX - ev.clientX)))
    const up = () => {
      handle.removeEventListener('pointermove', move)
      handle.removeEventListener('pointerup', up)
      write(PANEL_WIDTH, String(last))
    }
    handle.addEventListener('pointermove', move)
    handle.addEventListener('pointerup', up)
  }

  function resizeByKey(e: KeyboardEvent<HTMLElement>) {
    const step = e.key === 'ArrowLeft' ? 32 : e.key === 'ArrowRight' ? -32 : 0
    if (!step) return
    e.preventDefault()
    const next = clampWidth(width + step)
    setWidth(next)
    write(PANEL_WIDTH, String(next))
  }

  if (missing) {
    return (
      <Box component="main" sx={{ maxWidth: 960, mx: 'auto', px: 2, py: 6 }}>
        <Typography component="h1" sx={{ fontSize: 20, fontWeight: 600 }}>This workspace does not exist or was deleted</Typography>
        <Typography color="text.secondary">
          <Link component={RouterLink} to="/">Start a new workspace</Link>
        </Typography>
      </Box>
    )
  }

  const square = { width: 32, height: 32, border: 1, borderColor: 'divider', borderRadius: '8px' }
  return (
    <Box component="main" sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box component="header" sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 2, minHeight: 52, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          {renaming && live ? (
            <NameInput agent={live} onDone={(e) => (setRenaming(false), setError(e ?? ''))} sx={{ width: '100%', maxWidth: 420 }} />
          ) : (
            <Typography component="h1" sx={{ fontSize: 15, fontWeight: 500, minWidth: 0 }}>
              <ButtonBase
                onClick={() => setRenaming(true)}
                disabled={!live}
                title={live?.job || 'Rename'}
                aria-label={live ? `${live.name}, rename` : undefined}
                sx={{ maxWidth: '100%', px: 1, py: 0.5, ml: -1, borderRadius: '8px', font: 'inherit', justifyContent: 'flex-start', '&:hover': { bgcolor: 'var(--raised)' } }}
              >
                <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{live?.name ?? ''}</Box>
              </ButtonBase>
            </Typography>
          )}
        </Box>
        {statuses.length > 0 && (
          <Box component="span" sx={{ px: 1.25, py: '2px', border: 1, borderColor: 'divider', borderRadius: 999, fontFamily: MONO, fontSize: 12, color: 'text.secondary', whiteSpace: 'nowrap' }}>
            {statuses.length} changed
          </Box>
        )}
        <Tooltip title={stop ? 'Wait for the turn to end, or stop it' : 'New chat'}>
          <span>
            <IconButton aria-label="New chat" onClick={newChat} disabled={!!stop} sx={square}>
              <PostAdd sx={{ fontSize: 18 }} />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title={panelOpen ? 'Hide files' : 'Show files'}>
          <IconButton aria-label="Files and preview" aria-pressed={panelOpen} onClick={() => showPanel(!panelOpen)} sx={{ ...square, ...(panelOpen && { bgcolor: 'var(--accentSoft)' }) }}>
            <ViewSidebarOutlined sx={{ fontSize: 18, transform: 'scaleX(-1)' }} />
          </IconButton>
        </Tooltip>
        <IconButton aria-label="Workspace options" aria-haspopup="menu" disabled={!live} onClick={(e) => setMenu(e.currentTarget)} sx={square}>
          <MoreHoriz sx={{ fontSize: 18 }} />
        </IconButton>
      </Box>
      {/* Focus goes back to the options button by hand, except on Rename: there it belongs to the
          name field, and the menu's own restore (fixed when it opens) would end the rename at once. */}
      <Menu anchorEl={menu} open={!!menu} onClose={() => (menu?.focus(), setMenu(null))} disableRestoreFocus>
        <MenuItem onClick={() => (setRenaming(true), setMenu(null))}>Rename</MenuItem>
        <MenuItem onClick={() => (menu?.focus(), setDialog('purpose'), setMenu(null))}>Name and purpose…</MenuItem>
        <MenuItem onClick={() => (menu?.focus(), setDialog('delete'), setMenu(null))} sx={{ color: 'error.main' }}>Delete…</MenuItem>
      </Menu>
      {error && <Alert severity="error" onClose={() => setError('')} sx={{ borderRadius: 0 }}>{error}</Alert>}

      <Box sx={{ flexGrow: 1, minHeight: 0, display: 'flex', position: 'relative' }}>
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          <Chat
            key={chatEpoch}
            agentId={agentId}
            initial={chatEpoch === 0 ? initial : undefined}
            onTurnStart={turnStarted}
            onTurnDone={afterTurn}
            onTitle={titled}
            onRunning={running}
            onOpen={openFile}
          />
        </Box>
        {panelMounted && (
          <>
            {wideScreen && panelOpen && (
              <Box
                role="separator"
                aria-orientation="vertical"
                aria-label="Resize the files panel"
                aria-valuemin={MIN_WIDTH}
                aria-valuenow={width}
                tabIndex={0}
                onPointerDown={resize}
                onKeyDown={resizeByKey}
                sx={{ width: 6, mx: '-3px', zIndex: 1, cursor: 'col-resize', flexShrink: 0, '&:hover, &:focus-visible': { bgcolor: 'primary.main', outline: 'none' } }}
              />
            )}
            <Box
              sx={
                wideScreen
                  ? { width, flexShrink: 0, borderLeft: 1, borderColor: 'divider', display: panelOpen ? 'block' : 'none' }
                  : { position: 'absolute', inset: 0, zIndex: 2, display: panelOpen ? 'block' : 'none' }
              }
            >
              <WorkspacePanel
                agentId={agentId}
                tree={tree}
                letters={letters}
                storage={storage}
                files={files}
                version={version}
                view={view}
                onView={setView}
                onOpen={openFile}
                onRefresh={afterTurn}
                onCreate={create}
                onClose={() => showPanel(false)}
                wide={wideScreen && width >= 560}
              />
            </Box>
          </>
        )}
      </Box>

      {dialog === 'purpose' && live && (
        <AgentDialog
          title="Name and purpose"
          submitLabel="Save"
          initial={{ name: live.name, job: live.job }}
          onClose={() => setDialog(null)}
          onSubmit={async (value) => {
            const saved = await api<Agent>(`/api/agents/${agentId}`, { method: 'PATCH', body: value })
            setAgent(saved)
            upsert(saved)
            setDialog(null)
          }}
        />
      )}
      {dialog === 'delete' && live && <DeleteDialog agent={live} onClose={() => setDialog(null)} onDeleted={() => navigate('/')} />}

      <Dialog open={guard.asking} onClose={guard.stay}>
        <DialogTitle>The agent is still working</DialogTitle>
        <DialogContent>
          <Typography color="text.secondary">Leaving stops it. What it already changed stays in its files.</Typography>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={guard.stay} autoFocus>Stay</Button>
          <Button variant="contained" color="error" onClick={guard.leave}>Leave and stop</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
