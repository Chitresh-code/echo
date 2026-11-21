import { Alert, Box, Link, Typography } from '@mui/material'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, useParams } from 'react-router'
import { api, ApiError, errorText } from '../api/client'
import type { Agent as AgentRecord, GitFileStatus, Tree } from '../api/types'
import { Chat } from '../agent/Chat'
import { Editor } from '../agent/Editor'
import { Explorer } from '../agent/Explorer'
import { useOpenFiles } from '../agent/files'
import { statusLetters } from '../agent/tree'
import { TopBar } from '../layout/TopBar'
import { MONO } from '../theme'

export default function Agent() {
  const { agentId = '' } = useParams()
  // A new agent id means a new page: every panel starts fresh.
  return <AgentPage key={agentId} agentId={agentId} />
}

function AgentPage({ agentId }: { agentId: string }) {
  const [agent, setAgent] = useState<AgentRecord | null>(null)
  const [missing, setMissing] = useState(false)
  const [tree, setTree] = useState<Tree | null>(null)
  const [statuses, setStatuses] = useState<GitFileStatus[]>([])
  const [error, setError] = useState('')
  const files = useOpenFiles(agentId)
  const letters = useMemo(() => statusLetters(statuses), [statuses])

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
  }, [agentId])

  useEffect(() => {
    api<AgentRecord>(`/api/agents/${agentId}`).then(
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
  }, [refreshTree, refresh])

  async function create(path: string) {
    try {
      await api(`/api/agents/${agentId}/file`, { method: 'PUT', body: { path, content: '' } })
      await refreshTree()
      files.open(path, false)
    } catch (e) {
      setError(errorText(e))
    }
  }

  if (missing) {
    return (
      <Box sx={{ minHeight: '100%' }}>
        <TopBar />
        <Box sx={{ maxWidth: 960, mx: 'auto', px: 2, py: 6 }}>
          <Typography sx={{ fontSize: 20, fontWeight: 600 }}>There is no agent here</Typography>
          <Typography color="text.secondary">
            It may belong to another account. <Link component={RouterLink} to="/">Back to your agents</Link>
          </Typography>
        </Box>
      </Box>
    )
  }

  const panel = { borderColor: 'divider', minHeight: { xs: 480, md: 0 } }
  return (
    <Box sx={{ height: { md: '100vh' }, minHeight: '100%', display: 'flex', flexDirection: 'column' }}>
      <TopBar>
        <Box component="nav" aria-label="Breadcrumb" sx={{ display: 'flex', alignItems: 'center', gap: 1, color: 'text.secondary', minWidth: 0 }}>
          <Link component={RouterLink} to="/" underline="hover" sx={{ color: 'text.secondary' }}>Agents</Link>
          <span aria-hidden="true">/</span>
          <Typography component="span" title={agent?.job} sx={{ color: 'text.primary', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {agent?.name ?? ''}
          </Typography>
        </Box>
        {statuses.length > 0 && (
          <Box component="span" sx={{ px: 1.25, py: '2px', border: 1, borderColor: 'divider', borderRadius: 999, fontFamily: MONO, fontSize: 12, color: 'text.secondary' }}>
            {statuses.length} changed
          </Box>
        )}
      </TopBar>
      {error && <Alert severity="error" onClose={() => setError('')} sx={{ borderRadius: 0 }}>{error}</Alert>}
      <Box sx={{ flexGrow: 1, minHeight: 0, display: 'flex', flexDirection: { xs: 'column', md: 'row' } }}>
        <Box sx={{ ...panel, width: { md: 248 }, flexShrink: 0, borderRight: { md: 1 }, borderBottom: { xs: 1, md: 0 }, bgcolor: 'background.paper', minHeight: { xs: 240, md: 0 } }}>
          <Explorer tree={tree} letters={letters} active={files.active} onOpen={(p) => files.open(p, letters.has(p))} onRefresh={afterTurn} onCreate={create} />
        </Box>
        <Box sx={{ ...panel, flexGrow: 1, minWidth: 0 }}>
          <Editor agentId={agentId} files={files} letters={letters} />
        </Box>
        <Box sx={{ ...panel, width: { md: 400 }, flexShrink: 0, borderLeft: { md: 1 }, borderTop: { xs: 1, md: 0 } }}>
          <Chat agentId={agentId} onTurnDone={afterTurn} />
        </Box>
      </Box>
    </Box>
  )
}
