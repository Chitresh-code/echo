import DeleteOutline from '@mui/icons-material/DeleteOutlined'
import ForumOutlined from '@mui/icons-material/ForumOutlined'
import {
  Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Link, Popover, Tooltip, Typography,
} from '@mui/material'
import { useState } from 'react'
import { Link as RouterLink } from 'react-router'
import { api, errorText } from '../api/client'
import { ago } from '../format'
import { chatPath, chatsUrl, chatUrl, type ChatList as Page, type ChatSummary } from './chats'

type Props = {
  agentId: string
  /** The chat on screen, marked in the list. */
  current: string | null
  /** The chat on screen was deleted. */
  onDeletedCurrent: () => void
  sx?: object
}

/** This workspace's chats, newest first, from a header button. Loaded each time it opens, so a
 *  chat another tab started is there too. */
export function ChatList({ agentId, current, onDeletedCurrent, sx }: Props) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [chats, setChats] = useState<ChatSummary[] | null>(null)
  const [more, setMore] = useState(false)
  const [error, setError] = useState('')
  const [loadingMore, setLoadingMore] = useState(false)
  const [deleting, setDeleting] = useState<ChatSummary | null>(null)

  async function load(before?: string) {
    setError('')
    if (before) setLoadingMore(true)
    try {
      const page = await api<Page>(before ? `${chatsUrl(agentId)}?before=${before}` : chatsUrl(agentId))
      setChats((shown) => (before ? [...(shown ?? []), ...page.chats] : page.chats))
      setMore(page.more)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setLoadingMore(false)
    }
  }

  function show(el: HTMLElement) {
    setAnchor(el)
    setChats(null)
    void load()
  }

  const close = () => setAnchor(null)

  return (
    <>
      <Tooltip title="Chats">
        <IconButton aria-label="Chats" aria-haspopup="dialog" aria-expanded={!!anchor} onClick={(e) => show(e.currentTarget)} sx={sx}>
          <ForumOutlined sx={{ fontSize: 18 }} />
        </IconButton>
      </Tooltip>
      <Popover
        open={!!anchor}
        anchorEl={anchor}
        onClose={close}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        slotProps={{ paper: { role: 'dialog', 'aria-label': 'Chats', sx: { width: 'min(360px, calc(100vw - 32px))', maxHeight: '70vh', display: 'flex', flexDirection: 'column' } } }}
      >
        <Typography component="h2" sx={{ fontSize: 13, fontWeight: 600, px: 2, pt: 1.5, pb: 1 }}>Chats</Typography>
        <Box sx={{ overflowY: 'auto', pb: 1 }}>
          {error ? (
            <Alert severity="error" sx={{ mx: 1.5 }} action={<Button size="small" onClick={() => load()}>Retry</Button>}>
              The chats could not be loaded. {error}
            </Alert>
          ) : chats === null ? (
            <Box role="status" aria-label="Loading chats" sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
              <CircularProgress size={18} />
            </Box>
          ) : chats.length === 0 ? (
            <Typography color="text.secondary" sx={{ px: 2, py: 1, fontSize: 14 }}>No chats yet. The first message you send starts one.</Typography>
          ) : (
            <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0 }}>
              {chats.map((chat) => (
                <Box component="li" key={chat.id} sx={{ display: 'flex', alignItems: 'center', px: 1, '&:hover .delete, &:focus-within .delete': { opacity: 1 } }}>
                  <Link
                    component={RouterLink}
                    to={chatPath(agentId, chat.id)}
                    onClick={close}
                    underline="none"
                    color="inherit"
                    aria-current={chat.id === current ? 'page' : undefined}
                    sx={{ flexGrow: 1, minWidth: 0, px: 1, py: 0.75, borderRadius: '8px', bgcolor: chat.id === current ? 'var(--accentSoft)' : undefined, '&:hover': { bgcolor: 'var(--raised)' } }}
                  >
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {chat.running && <Box component="span" aria-hidden sx={{ width: 7, height: 7, borderRadius: '50%', bgcolor: 'primary.main', flexShrink: 0 }} />}
                      <Typography component="span" sx={{ fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{chat.title}</Typography>
                    </Box>
                    <Typography component="span" color="text.secondary" sx={{ fontSize: 12, display: 'block' }}>
                      {chat.running ? 'Working now' : ago(chat.updated_at)}
                    </Typography>
                  </Link>
                  <Tooltip title={chat.running ? 'Stop the turn or wait for it to end before deleting' : 'Delete chat'}>
                    <span>
                      <IconButton
                        className="delete"
                        aria-label={`Delete chat ${chat.title}`}
                        disabled={chat.running}
                        onClick={() => setDeleting(chat)}
                        size="small"
                        sx={{ opacity: { xs: 1, md: 0 } }}
                      >
                        <DeleteOutline sx={{ fontSize: 18 }} />
                      </IconButton>
                    </span>
                  </Tooltip>
                </Box>
              ))}
            </Box>
          )}
          {more && !error && (
            <Button size="small" onClick={() => load(chats?.at(-1)?.id)} disabled={loadingMore} sx={{ display: 'block', mx: 'auto', mt: 0.5 }}>
              {loadingMore ? 'Loading…' : 'Show more'}
            </Button>
          )}
        </Box>
      </Popover>
      {deleting && (
        <DeleteChat
          agentId={agentId}
          chat={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setChats((shown) => shown?.filter((c) => c.id !== deleting.id) ?? null)
            setDeleting(null)
            if (deleting.id === current) {
              close()
              onDeletedCurrent()
            }
          }}
        />
      )}
    </>
  )
}

/** Asks first; a refusal (a turn started meanwhile) stays in the dialog. */
function DeleteChat({ agentId, chat, onClose, onDeleted }: { agentId: string; chat: ChatSummary; onClose: () => void; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function confirm() {
    setBusy(true)
    setError('')
    try {
      await api(chatUrl(agentId, chat.id), { method: 'DELETE' })
      onDeleted()
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={onClose}>
      <DialogTitle>Delete {chat.title}?</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {error && <Alert severity="error">{error}</Alert>}
        <Typography color="text.secondary">
          Its messages and the agent's memory of it are removed for good. Files the agent changed and what it learned stay. This cannot be undone.
        </Typography>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" color="error" disabled={busy} onClick={confirm}>Delete</Button>
      </DialogActions>
    </Dialog>
  )
}
