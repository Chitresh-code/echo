import { Alert, Box, Button, Typography } from '@mui/material'
import { useState } from 'react'
import { Link as RouterLink, useNavigate } from 'react-router'
import { api, errorText } from '../api/client'
import type { Agent } from '../api/types'
import { ModelPicker, useModelChoice } from '../agent/ModelPicker'
import { useAuth } from '../auth'
import { Composer } from '../composer/Composer'
import { useWorkspaces } from '../layout/workspaces'

/** What the workspace page sends as its first turn, handed over in the navigation state. */
export type Handover = { send: string }

/** The page a signed-in user lands on: a message box, and each message starts a new workspace. */
export function Home() {
  const { user } = useAuth()
  const { upsert } = useWorkspaces()
  const navigate = useNavigate()
  const models = useModelChoice()
  const [error, setError] = useState('')
  const noKey = models.keys?.length === 0
  const first = user?.name?.split(' ')[0]

  async function start(markdown: string): Promise<boolean> {
    setError('')
    if (!models.choice) {
      setError('Choose a model below first.')
      return false
    }
    try {
      const agent = await api<Agent>('/api/agents', { method: 'POST', body: {} })
      upsert(agent)
      navigate(`/w/${agent.id}`, { state: { send: markdown } satisfies Handover })
      return true
    } catch (e) {
      setError(errorText(e))
      return false
    }
  }

  return (
    <Box component="main" sx={{ maxWidth: 760, minHeight: '100%', boxSizing: 'border-box', mx: 'auto', px: 2, py: 4, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 3 }}>
      <Typography component="h1" sx={{ fontSize: 28, fontWeight: 600, letterSpacing: '-0.01em', textAlign: 'center' }}>
        {first ? `What are we working on, ${first}?` : 'What are we working on?'}
      </Typography>
      {noKey && (
        <Alert
          severity="info"
          action={<Button component={RouterLink} to="/credentials" size="small" sx={{ minHeight: 32 }}>Add a key</Button>}
        >
          Add a model key to start a workspace.
        </Alert>
      )}
      {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
      <Composer
        draftKey="home"
        autoFocus
        disabled={noKey}
        onSend={start}
        placeholder="Ask Echo to build, fix or research something"
        footer={noKey ? null : <Box sx={{ display: 'flex', gap: 1, minWidth: 0 }}><ModelPicker state={models} disabled={false} /></Box>}
      />
      <Typography color="text.secondary" sx={{ fontSize: 13, textAlign: 'center' }}>
        Echo is AI and can make mistakes. Check its work.
      </Typography>
    </Box>
  )
}
