import PanTool from '@mui/icons-material/PanToolOutlined'
import { Alert, Box, Button, Typography } from '@mui/material'
import { useState } from 'react'
import { api, ApiError, errorText } from '../api/client'
import type { ApprovalRequest } from '../api/stream'
import type { ApprovalDecision } from '../api/types'
import { MONO } from '../theme'

export type ApprovalPart = ApprovalRequest & { kind: 'approval'; decision?: ApprovalDecision | 'timeout' }

const OUTCOME: Record<ApprovalDecision | 'timeout', string> = {
  allow: 'Allowed',
  always: 'Allowed for the rest of this chat',
  deny: 'Denied. The agent was told to ask you instead.',
  timeout: 'No one answered in 10 minutes, so the call did not run.',
}

/** Turns a server's tool hints into words, such as "read only" for readOnlyHint: true. */
export function hintWords(hints: Record<string, unknown> | null): string[] {
  if (!hints) return []
  const words: Record<string, string> = { readOnlyHint: 'read only', destructiveHint: 'may delete or overwrite', idempotentHint: 'safe to repeat', openWorldHint: 'reaches outside services' }
  return Object.entries(words).filter(([key]) => hints[key] === true).map(([, word]) => word)
}

type Props = {
  agentId: string
  part: ApprovalPart
  /** The turn is still running, so an unanswered card can be answered. */
  live: boolean
}

/** A tool call that waits for the user, in the reply where the call shows. The answer comes back
 *  on the turn's stream as approval_done, in this tab and any other one showing the chat. */
export function ApprovalCard({ agentId, part, live }: Props) {
  const [sending, setSending] = useState<ApprovalDecision | null>(null)
  const [error, setError] = useState('')
  const waiting = !part.decision && live
  const input = part.input_cut ? String(part.input) : JSON.stringify(part.input, null, 2)
  const hints = hintWords(part.hints)

  async function answer(decision: ApprovalDecision) {
    setSending(decision)
    setError('')
    try {
      await api(`/api/agents/${agentId}/approvals/${part.id}`, { method: 'POST', body: { decision } })
    } catch (e) {
      setSending(null)
      setError(e instanceof ApiError && e.status === 404 ? 'This request was already answered or has timed out.' : errorText(e))
    }
  }

  return (
    <Box
      role="group"
      aria-label={`Approval for ${part.tool}`}
      sx={{ border: 1, borderColor: waiting ? 'warning.main' : 'divider', borderRadius: '8px', p: 1.25, display: 'flex', flexDirection: 'column', gap: 1, fontSize: 13 }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <PanTool sx={{ fontSize: 16, color: waiting ? 'warning.main' : 'text.secondary' }} />
        <span>{waiting ? 'The agent wants to run' : 'The agent asked to run'}</span>
        <Box component="span" sx={{ fontFamily: MONO, fontWeight: 600 }}>{part.tool}</Box>
        {part.server && <Box component="span" sx={{ color: 'text.secondary' }}>from {part.server}</Box>}
      </Box>
      {part.subagent && <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Asked by a subagent working on: {part.subagent}</Typography>}
      <Box
        component="pre"
        tabIndex={0}
        aria-label="What the call will run with"
        sx={{ m: 0, p: 1, maxHeight: 240, overflow: 'auto', bgcolor: 'background.default', borderRadius: '6px', fontFamily: MONO, fontSize: 12, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}
      >
        {input}
      </Box>
      {part.input_cut && <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>Shown cut short. The call gets all of it.</Typography>}
      {hints.length > 0 && <Typography sx={{ fontSize: 12, color: 'text.secondary' }}>The server says: {hints.join(', ')}.</Typography>}
      {error && <Alert severity="error" sx={{ fontSize: 13 }}>{error}</Alert>}
      {waiting ? (
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          <Button size="small" variant="contained" disabled={!!sending} onClick={() => answer('allow')}>Allow</Button>
          <Button size="small" variant="outlined" disabled={!!sending} onClick={() => answer('always')}>Allow for this chat</Button>
          <Button size="small" color="error" disabled={!!sending} onClick={() => answer('deny')}>Deny</Button>
        </Box>
      ) : (
        <Typography role="status" sx={{ fontSize: 12, color: part.decision === 'allow' || part.decision === 'always' ? 'text.secondary' : 'text.primary' }}>
          {part.decision ? OUTCOME[part.decision] : 'The turn ended before this was answered, so the call did not run.'}
        </Typography>
      )}
    </Box>
  )
}
