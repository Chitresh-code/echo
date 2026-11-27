import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { api, errorText } from '../api/client'
import type { Agent, ApprovalMode, McpServer } from '../api/types'
import { matches, type Command, type CommandOption } from '../composer/commands'

const MODES: { id: ApprovalMode; label: string; detail: string }[] = [
  { id: 'ask', label: 'Ask before tools', detail: 'You approve commands, file changes and web requests first' },
  { id: 'yolo', label: 'Yolo', detail: 'Every call runs without asking' },
]

/**
 * The `/approvals` command, for a workspace the page already holds. The new mode shows at once and
 * is saved in the background; a refused save puts the old one back and says why through `onError`.
 * A running turn picks the change up on its next call, and yolo lets a waiting call run.
 */
export function useApprovalMode(agent: Agent | null, onSaved: (agent: Agent) => void, onError: (text: string) => void) {
  // The mode being saved, shown until the save settles.
  const [saving, setSaving] = useState<ApprovalMode | null>(null)
  const mode: ApprovalMode = saving ?? agent?.approval_mode ?? 'ask'

  const command: Command = {
    name: 'approvals',
    description: 'Whether the agent asks before tools that change something',
    options: (query) =>
      MODES.filter((m) => matches(m.label, query)).map((m) => ({ ...m, group: 'Approvals', selected: m.id === mode, disabled: !agent })),
    apply(option) {
      const next = option.id as ApprovalMode
      const said = next === 'yolo' ? 'Yolo on: tools run without asking' : 'The agent asks before tools that change something'
      if (!agent || next === mode) return said
      setSaving(next)
      api<Agent>(`/api/agents/${agent.id}`, { method: 'PATCH', body: { approval_mode: next } })
        .then(onSaved, (e) => onError(`Approvals were not changed. ${errorText(e)}`))
        .finally(() => setSaving(null))
      return said
    },
  }
  return { mode, command }
}

const NOT_READY: Partial<Record<McpServer['status'], string>> = {
  needs_auth: 'Needs connecting in Connectors',
  needs_scope: 'Needs reconnecting in Connectors',
  tools_changed: 'Tools changed: review them in Connectors',
}

/**
 * The MCP servers a workspace uses: `/mcp` and the checklist in Name and purpose share this state.
 * Each change saves the whole set; saves go one at a time so they reach the server in order, and a
 * refused one puts back the last saved set.
 */
export function useMcpServers(agentId: string, onError: (text: string) => void) {
  const navigate = useNavigate()
  const [servers, setServers] = useState<McpServer[] | null>(null)
  const [chosen, setChosen] = useState<string[]>([])
  const [loadError, setLoadError] = useState('')
  const saved = useRef<string[]>([])
  const queue = useRef(Promise.resolve())
  const latest = useRef(0)

  const load = useCallback(() => {
    setLoadError('')
    Promise.all([api<McpServer[]>('/api/mcp-servers'), api<McpServer[]>(`/api/agents/${agentId}/mcp-servers`)]).then(([all, mine]) => {
      saved.current = mine.map((s) => s.id)
      setServers(all)
      setChosen(saved.current)
    }, (e) => setLoadError(errorText(e)))
  }, [agentId])
  useEffect(load, [load])

  function save(ids: string[]): Promise<void> {
    const n = ++latest.current
    setChosen(ids)
    const run = queue.current.then(() => api<McpServer[]>(`/api/agents/${agentId}/mcp-servers`, { method: 'PUT', body: { server_ids: ids } }))
    queue.current = run.then(() => undefined, () => undefined)
    return run.then(
      (mine) => {
        saved.current = mine.map((s) => s.id)
        if (n === latest.current) setChosen(saved.current)
      },
      (e) => {
        if (n === latest.current) setChosen(saved.current)
        throw e
      },
    )
  }

  const command: Command = {
    name: 'mcp',
    description: 'The MCP servers this workspace uses',
    keepOpen: true,
    options(query) {
      if (loadError) return [{ id: 'retry', label: 'Retry', detail: `Your MCP servers could not be loaded. ${loadError}`, group: 'MCP servers' }]
      if (!servers) return [{ id: 'loading', label: 'Loading your MCP servers', disabled: true, group: 'MCP servers' }]
      const rows: CommandOption[] = servers.filter((s) => matches(s.name, query)).map((s) => ({
        id: s.id,
        label: s.name,
        detail: NOT_READY[s.status] ?? (s.kind === 'remote' ? s.url ?? '' : s.command ?? ''),
        group: 'MCP servers',
        selected: chosen.includes(s.id),
      }))
      return [...rows, servers.length
        ? { id: 'connectors', label: 'Open Connectors', detail: 'Add, connect or review servers', group: 'Connectors' }
        : { id: 'connectors', label: 'Add an MCP server', detail: 'You have none yet', group: 'Connectors' }]
    },
    apply(option) {
      if (option.id === 'retry') {
        load()
        return null
      }
      if (option.id === 'connectors') {
        navigate('/mcp')
        return 'Opening Connectors'
      }
      const on = !chosen.includes(option.id)
      save(on ? [...chosen, option.id] : chosen.filter((id) => id !== option.id))
        .catch((e) => onError(`MCP servers were not changed. ${errorText(e)}`))
      return on ? `${option.label} on for this workspace` : `${option.label} off for this workspace`
    },
  }
  return { servers, chosen, save, command }
}
