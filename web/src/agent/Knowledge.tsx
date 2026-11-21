import DeleteOutline from '@mui/icons-material/DeleteOutlined'
import ErrorOutline from '@mui/icons-material/ErrorOutlined'
import WarningAmber from '@mui/icons-material/WarningAmber'
import { Alert, Box, Button, ButtonBase, IconButton, Tooltip, Typography } from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Note, Skills as SkillList } from '../api/types'
import { ago } from '../format'
import { MONO } from '../theme'

// Both lists reload when `version` changes, which the page bumps after every turn.
type Props = { agentId: string; version: number }

const empty = { px: 2, py: 1.5, fontSize: 12 }
const list = { listStyle: 'none', m: 0, p: 0, overflow: 'auto', flexGrow: 1 }

export function Skills({ agentId, version, onOpen }: Props & { onOpen: (path: string) => void }) {
  const [data, setData] = useState<SkillList | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<SkillList>(`/api/agents/${agentId}/skills`).then(setData, (e) => setError(errorText(e)))
  }, [agentId, version])

  if (error) return <Alert severity="error" sx={{ m: 1 }}>{error}</Alert>
  if (data && data.skills.length === 0) {
    return <Typography color="text.secondary" sx={empty}>No skills yet. Correct the agent in a chat and it saves what it learns here.</Typography>
  }
  return (
    <Box component="ul" aria-label="Skills" sx={list}>
      {data?.skills.map((s) => (
        <li key={s.name}>
          <ButtonBase onClick={() => onOpen(s.path)} sx={{ width: '100%', display: 'block', textAlign: 'left', px: 2, py: 1, '&:hover': { bgcolor: 'var(--raised)' } }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
              <Box component="span" sx={{ fontFamily: MONO, fontSize: 13, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexGrow: 1 }}>{s.name}</Box>
              {s.status !== 'ok' && (
                <Tooltip title={`${s.status === 'skipped' ? 'Not loaded. ' : ''}${s.problem ?? ''}`}>
                  {s.status === 'skipped'
                    ? <ErrorOutline aria-label="Not loaded" sx={{ fontSize: 16, color: 'error.main' }} />
                    : <WarningAmber aria-label="Has a problem" sx={{ fontSize: 16, color: 'warning.main' }} />}
                </Tooltip>
              )}
            </Box>
            {s.description && (
              <Typography color="text.secondary" sx={{ fontSize: 12, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                {s.description}
              </Typography>
            )}
          </ButtonBase>
        </li>
      ))}
      {data?.truncated && <Typography component="li" color="text.secondary" sx={empty}>Only the first {data.skills.length} skills are shown.</Typography>}
    </Box>
  )
}

export function Notes({ agentId, version }: Props) {
  const [notes, setNotes] = useState<Note[] | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(() => api<Note[]>(`/api/agents/${agentId}/notes`).then(setNotes, (e) => setError(errorText(e))), [agentId])
  useEffect(() => {
    load()
  }, [load, version])

  async function remove(name: string) {
    setConfirming(null)
    try {
      await api(`/api/agents/${agentId}/notes/${encodeURIComponent(name)}`, { method: 'DELETE' })
      await load()
    } catch (e) {
      setError(errorText(e))
    }
  }

  return (
    <>
      {error && <Alert severity="error" onClose={() => setError('')} sx={{ m: 1 }}>{error}</Alert>}
      {notes?.length === 0 && <Typography color="text.secondary" sx={empty}>No notes yet. The agent keeps short notes from each chat.</Typography>}
      <Box component="ul" aria-label="Notes" sx={list}>
        {notes?.map((n) => (
          <Box component="li" key={n.name} sx={{ px: 2, py: 1, borderBottom: 1, borderColor: 'divider' }}>
            <Typography sx={{ fontSize: 13, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{n.text}</Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5 }}>
              <Typography color="text.secondary" sx={{ fontSize: 12, flexGrow: 1 }}>{ago(n.updated_at)}</Typography>
              {confirming === n.name ? (
                <>
                  <Button size="small" color="error" onClick={() => remove(n.name)}>Forget</Button>
                  <Button size="small" onClick={() => setConfirming(null)}>Keep</Button>
                </>
              ) : (
                <Tooltip title="Forget this note">
                  <IconButton size="small" aria-label="Forget this note" onClick={() => setConfirming(n.name)}>
                    <DeleteOutline sx={{ fontSize: 16 }} />
                  </IconButton>
                </Tooltip>
              )}
            </Box>
          </Box>
        ))}
      </Box>
    </>
  )
}
