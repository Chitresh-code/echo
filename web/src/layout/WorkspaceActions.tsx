import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, InputBase, Typography, type SxProps, type Theme } from '@mui/material'
import { useState } from 'react'
import { errorText } from '../api/client'
import type { Agent } from '../api/types'
import { useWorkspaces } from './workspaces'

// The api's limit on a workspace name.
export const NAME_CHARS = 80

/** Renames a workspace in place. Enter or leaving the field saves, Escape cancels; both end in
 *  blur, the one place that saves, so a name is never sent twice. */
export function NameInput({ agent, onDone, sx }: { agent: Agent; onDone: (error?: string) => void; sx?: SxProps<Theme> }) {
  const { rename } = useWorkspaces()
  async function save(value: string) {
    const name = value.trim()
    if (!name || name === agent.name) return onDone()
    onDone()
    try {
      await rename(agent.id, name)
    } catch (e) {
      onDone(`Could not rename "${agent.name}": ${errorText(e)}`)
    }
  }
  return (
    <InputBase
      autoFocus
      defaultValue={agent.name}
      onFocus={(e) => e.target.select()}
      onBlur={(e) => save(e.target.value)}
      onKeyDown={(e) => {
        const input = e.target as HTMLInputElement
        if (e.key === 'Escape') input.value = agent.name
        if (e.key === 'Enter' || e.key === 'Escape') input.blur()
      }}
      inputProps={{ 'aria-label': 'Workspace name', maxLength: NAME_CHARS }}
      sx={{ minHeight: 36, px: 1.25, border: 1, borderColor: 'primary.main', borderRadius: '8px', fontSize: 14, ...sx }}
    />
  )
}

/** Asks before deleting; a refusal (such as a turn in progress) stays in the dialog. */
export function DeleteDialog({ agent, onClose, onDeleted }: { agent: Agent; onClose: () => void; onDeleted: () => void }) {
  const { remove } = useWorkspaces()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function confirm() {
    setBusy(true)
    setError('')
    try {
      await remove(agent.id)
      onDeleted()
    } catch (e) {
      setError(errorText(e))
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={onClose}>
      <DialogTitle>Delete {agent.name}?</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {error && <Alert severity="error">{error}</Alert>}
        <Typography color="text.secondary">Its files, skills, notes and chats are removed for good. This cannot be undone.</Typography>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" color="error" disabled={busy} onClick={confirm}>Delete</Button>
      </DialogActions>
    </Dialog>
  )
}
