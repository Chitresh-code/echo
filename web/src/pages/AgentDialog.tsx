import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, TextField } from '@mui/material'
import { useState } from 'react'
import { errorText } from '../api/client'

type Props = {
  title: string
  submitLabel: string
  initial?: { name: string; job: string }
  onSubmit: (value: { name: string; job: string }) => Promise<void>
  onClose: () => void
}

/** Name and job of an agent, for creating one or changing it. */
export function AgentDialog({ title, submitLabel, initial, onSubmit, onClose }: Props) {
  const [name, setName] = useState(initial?.name ?? '')
  const [job, setJob] = useState(initial?.job ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await onSubmit({ name: name.trim(), job: job.trim() })
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
          label="Job"
          value={job}
          onChange={(e) => setJob(e.target.value)}
          multiline
          minRows={3}
          placeholder="The one task you will teach it, such as: Match Stripe payouts to the ledger each week"
          helperText={`${job.length}/500`}
          slotProps={{ htmlInput: { maxLength: 500 } }}
        />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button type="submit" variant="contained" disabled={busy || !name.trim()}>{submitLabel}</Button>
      </DialogActions>
    </Dialog>
  )
}
