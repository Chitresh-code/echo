import { Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, Link, Switch, TextField, Typography } from '@mui/material'
import { Link as RouterLink } from 'react-router'
import { useState } from 'react'
import { errorText } from '../api/client'
import type { ApprovalMode, McpServer } from '../api/types'

type Value = { name: string; job: string; approval_mode: ApprovalMode }
type Props = {
  title: string
  submitLabel: string
  initial?: Value
  onSubmit: (value: Value) => Promise<void>
  onClose: () => void
  /** The workspace's MCP servers, shared with `/mcp`; left out when creating a workspace. */
  mcp?: { servers: McpServer[] | null; chosen: string[]; save: (ids: string[]) => Promise<void> }
}

/** A workspace's name and purpose, which the agent working in it reads each turn, and whether it asks before tools. */
export function AgentDialog({ title, submitLabel, initial, onSubmit, onClose, mcp }: Props) {
  // Null until a box is changed: the list may still be loading when the dialog opens.
  const [picked, setPicked] = useState<string[] | null>(null)
  const servers = picked ?? mcp?.chosen ?? []
  const [name, setName] = useState(initial?.name ?? '')
  const [job, setJob] = useState(initial?.job ?? '')
  const [mode, setMode] = useState<ApprovalMode>(initial?.approval_mode ?? 'ask')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      // The servers first: if they are refused, nothing else has changed yet.
      if (mcp && picked && (picked.length !== mcp.chosen.length || picked.some((id) => !mcp.chosen.includes(id)))) await mcp.save(picked)
      await onSubmit({ name: name.trim(), job: job.trim(), approval_mode: mode })
    } catch (err) {
      setError(errorText(err))
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm" slotProps={{ paper: { component: 'form', onSubmit: submit } as object }}>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '8px !important' }}>
        {error && <Alert severity="error">{error}</Alert>}
        <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} required autoFocus slotProps={{ htmlInput: { maxLength: 80 } }} />
        <TextField
          label="Purpose"
          value={job}
          onChange={(e) => setJob(e.target.value)}
          multiline
          minRows={3}
          placeholder="What this workspace is for, such as: Match Stripe payouts to the ledger each week"
          helperText={`${job.length}/500`}
          slotProps={{ htmlInput: { maxLength: 500 } }}
        />
        <FormControlLabel
          control={<Switch checked={mode === 'ask'} onChange={(e) => setMode(e.target.checked ? 'ask' : 'yolo')} />}
          label="Ask before the agent runs commands, changes files or reaches the web"
        />
        {mcp?.servers && (
          <Box role="group" aria-labelledby="mcp-servers-label">
            <Typography id="mcp-servers-label" sx={{ fontSize: 13, fontWeight: 500 }}>MCP servers</Typography>
            {mcp.servers.length === 0 ? (
              <Typography color="text.secondary" sx={{ fontSize: 13, mt: 0.5 }}>
                You have none yet. <Link component={RouterLink} to="/mcp">Add one in Connectors</Link>.
              </Typography>
            ) : (
              mcp.servers.map((s) => (
                <FormControlLabel
                  key={s.id}
                  sx={{ display: 'flex' }}
                  control={<Checkbox size="small" checked={servers.includes(s.id)} onChange={(e) => setPicked(e.target.checked ? [...servers, s.id] : servers.filter((id) => id !== s.id))} />}
                  label={<span>{s.name}{s.status !== 'ok' && <Typography component="span" color="text.secondary" sx={{ fontSize: 12 }}> · needs attention in Connectors</Typography>}</span>}
                />
              ))
            )}
          </Box>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button type="submit" variant="contained" disabled={busy || !name.trim()}>{submitLabel}</Button>
      </DialogActions>
    </Dialog>
  )
}
