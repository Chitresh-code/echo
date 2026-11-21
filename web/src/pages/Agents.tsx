import Add from '@mui/icons-material/Add'
import EditOutlined from '@mui/icons-material/EditOutlined'
import Search from '@mui/icons-material/Search'
import { Alert, Box, Button, IconButton, InputBase, Link, Tooltip, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { Link as RouterLink, useNavigate } from 'react-router'
import { api, errorText } from '../api/client'
import type { Agent } from '../api/types'
import { ago } from '../format'
import { TopBar } from '../layout/TopBar'
import { AgentDialog } from './AgentDialog'

export function Agents() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<Agent[] | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Agent | null>(null)

  useEffect(() => {
    api<Agent[]>('/api/agents').then(setAgents, (e) => setError(errorText(e)))
  }, [])

  const q = query.trim().toLowerCase()
  const shown = (agents ?? []).filter((a) => !q || a.name.toLowerCase().includes(q) || a.job.toLowerCase().includes(q))

  return (
    <Box sx={{ minHeight: '100%', display: 'flex', flexDirection: 'column' }}>
      <TopBar />
      <Box component="main" sx={{ width: '100%', maxWidth: 960, mx: 'auto', px: 2, py: 6, display: 'flex', flexDirection: 'column', gap: 3 }}>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 2 }}>
          <Box sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
            <Typography component="h1" sx={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.01em' }}>Your agents</Typography>
            <Typography color="text.secondary">Each one learns a single job from you and keeps what it learns.</Typography>
          </Box>
          <Button variant="contained" startIcon={<Add />} onClick={() => setCreating(true)}>New agent</Button>
        </Box>

        {error && <Alert severity="error">{error}</Alert>}

        {agents && agents.length > 0 && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, minHeight: 40, border: 1, borderColor: 'divider', borderRadius: '10px', bgcolor: 'background.paper' }}>
            <Search fontSize="small" sx={{ color: 'text.secondary' }} />
            <InputBase type="search" placeholder="Find an agent" value={query} onChange={(e) => setQuery(e.target.value)} sx={{ flexGrow: 1 }} inputProps={{ 'aria-label': 'Find an agent' }} />
          </Box>
        )}

        {agents && agents.length === 0 && (
          <Box sx={{ p: 5, border: 1, borderColor: 'divider', borderRadius: '12px', bgcolor: 'background.paper', textAlign: 'center', display: 'flex', flexDirection: 'column', gap: 1, alignItems: 'center' }}>
            <Typography sx={{ fontWeight: 600, fontSize: 16 }}>No agents yet</Typography>
            <Typography color="text.secondary" sx={{ maxWidth: 440 }}>
              Create one for a task you repeat. Give it a name and describe the job; it learns the rest by working with you.
            </Typography>
          </Box>
        )}

        {shown.length > 0 && (
          <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0, border: 1, borderColor: 'divider', borderRadius: '12px', bgcolor: 'background.paper', overflow: 'hidden' }}>
            {shown.map((agent, i) => (
              <Box component="li" key={agent.id} sx={{ display: 'flex', alignItems: 'center', borderTop: i ? 1 : 0, borderColor: 'divider', '&:hover': { bgcolor: 'var(--raised)' } }}>
                <Link
                  component={RouterLink}
                  to={`/agents/${agent.id}`}
                  underline="none"
                  sx={{ flexGrow: 1, minWidth: 0, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px 24px', py: 2, pl: 2.5, color: 'text.primary' }}
                >
                  <Box sx={{ flex: '1 1 260px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                    <Typography sx={{ fontWeight: 600, fontSize: 15 }}>{agent.name}</Typography>
                    <Typography color="text.secondary" sx={{ fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {agent.job || 'Not taught anything yet'}
                    </Typography>
                  </Box>
                  <Typography color="text.secondary" sx={{ minWidth: 120, fontSize: 13, textAlign: 'right' }}>
                    {agent.last_used_at ? `Used ${ago(agent.last_used_at)}` : `Created ${ago(agent.created_at)}`}
                  </Typography>
                </Link>
                <Tooltip title="Rename or change job">
                  <IconButton aria-label={`Edit ${agent.name}`} onClick={() => setEditing(agent)} sx={{ mx: 1.5 }} size="small">
                    <EditOutlined fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Box>
            ))}
          </Box>
        )}
        {agents && agents.length > 0 && shown.length === 0 && <Typography color="text.secondary">No agent matches "{query}".</Typography>}
      </Box>

      {creating && (
        <AgentDialog
          title="New agent"
          submitLabel="Create agent"
          onClose={() => setCreating(false)}
          onSubmit={async (value) => {
            const agent = await api<Agent>('/api/agents', { method: 'POST', body: value })
            navigate(`/agents/${agent.id}`)
          }}
        />
      )}
      {editing && (
        <AgentDialog
          title="Edit agent"
          submitLabel="Save"
          initial={editing}
          onClose={() => setEditing(null)}
          onSubmit={async (value) => {
            const agent = await api<Agent>(`/api/agents/${editing.id}`, { method: 'PATCH', body: value })
            setAgents((all) => all?.map((a) => (a.id === agent.id ? agent : a)) ?? null)
            setEditing(null)
          }}
        />
      )}
    </Box>
  )
}
