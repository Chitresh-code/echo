import MoreHoriz from '@mui/icons-material/MoreHoriz'
import PostAdd from '@mui/icons-material/PostAdd'
import ViewSidebarOutlined from '@mui/icons-material/ViewSidebarOutlined'
import {
  Alert, Box, ButtonBase, IconButton, Link, Menu, MenuItem, Tooltip, Typography, useMediaQuery,
} from '@mui/material'
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { Link as RouterLink, useLocation, useNavigate, useParams } from 'react-router'
import { api, ApiError, errorText } from '../api/client'
import type { Agent, GitFileStatus, Storage, Tree } from '../api/types'
import { Chat } from '../agent/Chat'
import { ChatList } from '../agent/ChatList'
import { chatPath, takeOldChat } from '../agent/chats'
import type { NewKind } from '../agent/Explorer'
import { useOpenFiles } from '../agent/files'
import { statusLetters } from '../agent/tree'
import { WorkspacePanel } from '../agent/WorkspacePanel'
import { read, write } from '../storage'
import { DeleteDialog, NameInput } from '../layout/WorkspaceActions'
import { useWorkspaces } from '../layout/workspaces'
import { MONO } from '../theme'
import { AgentDialog } from './AgentDialog'
import { useMcpServers } from '../agent/workspaceCommands'
import type { Handover } from './Home'

const PANEL = 'echo.panel'
const PANEL_WIDTH = 'echo.panel.width'
// The panel is never narrower than a usable editor, nor wider than leaves the chat readable.
const MIN_WIDTH = 320
const MAX_SHARE = 0.6
const DEFAULT_WIDTH = 640

const clampWidth = (w: number) => Math.round(Math.max(MIN_WIDTH, Math.min(w, window.innerWidth * MAX_SHARE)))

export default function Workspace() {
  const { agentId = '', chatId = null } = useParams()
  // A new workspace id means a new page: every panel starts fresh.
  return <WorkspacePage key={agentId} agentId={agentId} chatId={chatId} />
}

function WorkspacePage({ agentId, chatId }: { agentId: string; chatId: string | null }) {
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
    else if (!chatId) {
      // A tab open from before chats had addresses goes back to the chat it was in.
      const old = takeOldChat(agentId)
      if (old) navigate(chatPath(agentId, old), { replace: true })
    }
  }, [initial, location.pathname, navigate, agentId, chatId])

  // The chat on screen. A new chat getting its address keeps the same Chat, mid-turn; any other
  // change of address (New chat, the chat list, back and forward) opens the chat it names.
  const [shown, setShown] = useState({ key: 0, id: chatId })
  const adoptedId = useRef<string | null>(null)
  if (shown.id !== chatId) setShown({ key: chatId && chatId === adoptedId.current ? shown.key : shown.key + 1, id: chatId })
  const adopted = (id: string) => {
    adoptedId.current = id
    navigate(chatPath(agentId, id), { replace: true })
  }

  const [agent, setAgent] = useState<Agent | null>(null)
  const [missing, setMissing] = useState(false)
  const [tree, setTree] = useState<Tree | null>(null)
  const [statuses, setStatuses] = useState<GitFileStatus[]>([])
  const [storage, setStorage] = useState<Storage | null>(null)
  const [error, setError] = useState('')
  // Kept apart from error, which a tree refresh clears.
  const [notice, setNotice] = useState('')
  const [mcpError, setMcpError] = useState('')
  const mcp = useMcpServers(agentId, setMcpError)
  const [version, setVersion] = useState(0)
  const [renaming, setRenaming] = useState(false)
  const [menu, setMenu] = useState<HTMLElement | null>(null)
  const [dialog, setDialog] = useState<'purpose' | 'delete' | null>(null)
  const [panelOpen, setPanelOpen] = useState(() => read(PANEL) === 'open')
  // Mounted the first time it opens and kept after, so unsaved edits survive closing it.
  const [panelMounted, setPanelMounted] = useState(panelOpen)
  const [width, setWidth] = useState(() => clampWidth(Number(read(PANEL_WIDTH)) || DEFAULT_WIDTH))
  const files = useOpenFiles(agentId)
  const letters = useMemo(() => statusLetters(statuses), [statuses])

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

  const saved = useCallback((a: Agent) => (setAgent(a), upsert(a)), [upsert])

  const titled = useCallback((name: string) => {
    const current = liveRef.current
    if (current) upsert({ ...current, name })
  }, [upsert])

  function showPanel(open: boolean) {
    setPanelOpen(open)
    if (open) setPanelMounted(true)
    write(PANEL, open ? 'open' : 'closed')
  }

  const openFile = (path: string) => {
    showPanel(true)
    files.open(path, letters.has(path))
  }

  // Errors go back to the explorer's name box, which says what to change.
  async function create(kind: NewKind, path: string) {
    if (kind === 'folder') await api(`/api/agents/${agentId}/folders`, { method: 'POST', body: { path } })
    else await api(`/api/agents/${agentId}/file`, { method: 'PUT', body: { path, content: '', create: true } })
    await refreshTree()
    if (kind === 'file') files.open(path, false)
  }

  // A running turn goes on without this page, and stays in the chat list to come back to.
  const newChat = () => navigate(chatPath(agentId, null))

  const chatGone = useCallback(() => {
    setNotice('This chat does not exist. It may have been deleted. You are in a new chat.')
    navigate(chatPath(agentId, null), { replace: true })
  }, [agentId, navigate])

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
        <ChatList agentId={agentId} current={shown.id} onDeletedCurrent={() => navigate(chatPath(agentId, null), { replace: true })} sx={square} />
        <Tooltip title="New chat">
          <IconButton aria-label="New chat" onClick={newChat} sx={square}>
            <PostAdd sx={{ fontSize: 18 }} />
          </IconButton>
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
      {mcpError && <Alert severity="error" onClose={() => setMcpError('')} sx={{ borderRadius: 0 }}>{mcpError}</Alert>}
      {error && <Alert severity="error" onClose={() => setError('')} sx={{ borderRadius: 0 }}>{error}</Alert>}
      {notice && <Alert severity="info" onClose={() => setNotice('')} sx={{ borderRadius: 0 }}>{notice}</Alert>}

      <Box sx={{ flexGrow: 1, minHeight: 0, display: 'flex', position: 'relative' }}>
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          <Chat
            key={shown.key}
            agentId={agentId}
            agent={agent}
            onAgent={saved}
            chatId={shown.id}
            initial={shown.key === 0 ? initial : undefined}
            onChatId={adopted}
            onMissing={chatGone}
            onTurnStart={turnStarted}
            onTurnDone={afterTurn}
            onTitle={titled}
            onOpen={openFile}
            mcp={mcp.command}
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
                open={panelOpen}
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
          initial={{ name: live.name, job: live.job, approval_mode: agent?.approval_mode ?? 'ask' }}
          mcp={mcp}
          onClose={() => setDialog(null)}
          onSubmit={async (value) => {
            saved(await api<Agent>(`/api/agents/${agentId}`, { method: 'PATCH', body: value }))
            setDialog(null)
          }}
        />
      )}
      {dialog === 'delete' && live && <DeleteDialog agent={live} onClose={() => setDialog(null)} onDeleted={() => navigate('/')} />}

    </Box>
  )
}
