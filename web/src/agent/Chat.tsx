import AccountTree from '@mui/icons-material/AccountTree'
import AutoStories from '@mui/icons-material/AutoStories'
import CheckCircleOutline from '@mui/icons-material/CheckCircleOutlineOutlined'
import ChevronRight from '@mui/icons-material/ChevronRight'
import ErrorOutlined from '@mui/icons-material/ErrorOutlined'
import ExpandMore from '@mui/icons-material/ExpandMore'
import RadioButtonUnchecked from '@mui/icons-material/RadioButtonUnchecked'
import Terminal from '@mui/icons-material/Terminal'
import { Alert, Box, Button, ButtonBase, CircularProgress, Link, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError, errorText } from '../api/client'
import { streamTurn, type PlanItem, type TurnEvent } from '../api/stream'
import type { Agent, Usage } from '../api/types'
import { compact } from '../format'
import { MONO } from '../theme'
import type { Command } from '../composer/commands'
import { Composer, writeDraft } from '../composer/Composer'
import { ApprovalCard, type ApprovalPart } from './ApprovalCard'
import { Markdown } from './Markdown'
import { SettingsLabel } from '../composer/SettingsLabel'
import { useModelChoice } from './modelChoice'
import { useApprovalMode } from './workspaceCommands'
import { chatsUrl, chatUrl, INTERRUPTED, seconds, TRUNCATED, turnUrl, type ChatDetail, type StoredTurn } from './chats'

// ok is missing until the call's result arrives.
type ToolPart = { kind: 'tool'; id: string; name: string; skill?: string; detail?: string; ok?: boolean }
// A subagent, in place of the subagent call that started it.
type DelegatePart = { kind: 'delegate'; id: string; task: string; tools: ToolPart[]; ok?: boolean }
// An MCP server the turn could not use: the reason the agent was given, and for the user only, what the server said.
type UnavailablePart = { kind: 'unavailable'; server: string; reason: string; detail: string }
type Part = { kind: 'text'; text: string } | ToolPart | DelegatePart | { kind: 'plan'; items: PlanItem[] } | ApprovalPart | UnavailablePart
type Message =
  | { role: 'user'; text: string }
  | { role: 'agent'; parts: Part[]; usage?: Usage; learned?: string[]; seconds?: number; error?: string; stopped?: boolean; truncated?: boolean }
type AgentMessage = Extract<Message, { role: 'agent' }>

// The plan shows what todo_write wrote, and checking on background tasks says nothing to the user.
const HIDDEN_TOOLS = new Set(['todo_write', 'strands_manage_background_task'])

const updateTool = (tools: ToolPart[], id: string, change: Partial<ToolPart>) => tools.map((t) => (t.id === id ? { ...t, ...change } : t))

/** Adds one stream event to the agent's message: text joins the text before it, each tool gets a
 *  row, a subagent replaces the row of the call that started it, and the plan is kept in one place. */
export function apply(message: AgentMessage, event: TurnEvent): AgentMessage {
  const parts = [...message.parts]
  const last = parts.at(-1)
  const tools = (change: (p: ToolPart) => ToolPart, id: string) => parts.map((p) => (p.kind === 'tool' && p.id === id ? change(p) : p))
  const delegate = (id: string, change: (p: DelegatePart) => DelegatePart) => parts.map((p) => (p.kind === 'delegate' && p.id === id ? change(p) : p))
  switch (event.event) {
    case 'text':
      if (last?.kind === 'text') parts[parts.length - 1] = { ...last, text: last.text + event.data.text }
      else parts.push({ kind: 'text', text: event.data.text })
      return { ...message, parts }
    case 'tool':
      if (HIDDEN_TOOLS.has(event.data.name)) return message
      return { ...message, parts: [...parts, { kind: 'tool' as const, id: event.data.id, name: event.data.name }] }
    case 'skill':
      return { ...message, parts: tools((p) => ({ ...p, skill: event.data.name }), event.data.id) }
    case 'tool_detail':
      return { ...message, parts: tools((p) => ({ ...p, detail: event.data.detail }), event.data.id) }
    case 'tool_result':
      return { ...message, parts: tools((p) => ({ ...p, ok: event.data.ok }), event.data.id) }
    case 'todos': {
      const at = parts.findIndex((p) => p.kind === 'plan')
      if (at < 0) return { ...message, parts: [...parts, { kind: 'plan', items: event.data.items }] }
      parts[at] = { kind: 'plan', items: event.data.items }
      return { ...message, parts }
    }
    case 'delegate': {
      const block: DelegatePart = { kind: 'delegate', id: event.data.id, task: event.data.task, tools: [] }
      const at = parts.findIndex((p) => p.kind === 'tool' && p.id === event.data.id)
      if (at < 0) return { ...message, parts: [...parts, block] }
      parts[at] = block
      return { ...message, parts }
    }
    case 'delegate_tool': {
      const { delegate: id, ...tool } = event.data
      if (HIDDEN_TOOLS.has(tool.name)) return message
      return { ...message, parts: delegate(id, (p) => ({ ...p, tools: [...p.tools, { kind: 'tool', ...tool }] })) }
    }
    case 'delegate_tool_result':
      return { ...message, parts: delegate(event.data.delegate, (p) => ({ ...p, tools: updateTool(p.tools, event.data.id, { ok: event.data.ok }) })) }
    case 'delegate_done':
      return { ...message, parts: delegate(event.data.id, (p) => ({ ...p, ok: event.data.ok })) }
    case 'approval_needed':
      return { ...message, parts: [...parts, { kind: 'approval', ...event.data }] }
    case 'approval_done':
      return { ...message, parts: parts.map((p) => (p.kind === 'approval' && p.id === event.data.id ? { ...p, decision: event.data.decision } : p)) }
    case 'mcp_unavailable':
      return { ...message, parts: [...parts, { kind: 'unavailable', ...event.data, detail: event.data.detail ?? '' }] }
    case 'done':
      return { ...message, usage: event.data.usage, learned: event.data.learned }
    case 'error':
      return { ...message, error: event.data.request_id ? `${event.data.message} (request ${event.data.request_id})` : event.data.message }
    case 'stopped':
      return { ...message, stopped: true }
    case 'turn':
    case 'title':
      return message
  }
}

/** A stored chat as messages, rebuilt from each turn's events the same way they were shown live. */
export function fromTurns(turns: StoredTurn[]): Message[] {
  return turns.flatMap((turn): Message[] => {
    const agent = turn.events.reduce(apply, { role: 'agent', parts: [] } as AgentMessage)
    return [
      { role: 'user', text: turn.prompt },
      {
        ...agent,
        seconds: seconds(turn),
        truncated: turn.truncated || undefined,
        error: agent.error ?? (turn.status === 'interrupted' ? INTERRUPTED : undefined),
      },
    ]
  })
}

const rowSx = { display: 'flex', alignItems: 'center', gap: 1, px: 1.25, py: 0.75, border: 1, borderColor: 'divider', borderRadius: '8px', bgcolor: 'background.default', fontSize: 12, minWidth: 0 } as const
const ellipsis = { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 } as const

function ToolRow({ tool }: { tool: ToolPart }) {
  const failed = tool.ok === false
  return (
    <Box sx={{ ...rowSx, ...(failed && { borderColor: 'error.main' }) }}>
      {failed ? (
        <ErrorOutlined aria-label="Failed" sx={{ fontSize: 14, color: 'error.main' }} />
      ) : tool.skill !== undefined ? (
        <AutoStories sx={{ fontSize: 14, color: 'primary.main' }} />
      ) : (
        <Terminal sx={{ fontSize: 14, color: 'text.secondary' }} />
      )}
      <Box component="span" sx={{ fontFamily: MONO, color: 'text.secondary', fontWeight: 600, flexShrink: 0 }}>{tool.name}</Box>
      {tool.skill ? (
        <Box component="span" sx={{ color: 'text.secondary', ...ellipsis }}>used {tool.skill}</Box>
      ) : (
        tool.detail && <Box component="span" title={tool.detail} sx={{ fontFamily: MONO, color: 'text.secondary', ...ellipsis }}>{tool.detail}</Box>
      )}
    </Box>
  )
}

function DelegateBlock({ part, running }: { part: DelegatePart; running: boolean }) {
  const [open, setOpen] = useState(true)
  const status =
    part.ok === true ? (
      <CheckCircleOutline aria-label="Finished" sx={{ fontSize: 14, color: 'success.main' }} />
    ) : part.ok === false ? (
      <ErrorOutlined aria-label="Failed" sx={{ fontSize: 14, color: 'error.main' }} />
    ) : running ? (
      <CircularProgress aria-label="Running" size={12} />
    ) : null
  return (
    <Box sx={{ border: 1, borderColor: part.ok === false ? 'error.main' : 'divider', borderRadius: '8px', fontSize: 12 }}>
      <ButtonBase onClick={() => setOpen(!open)} aria-expanded={open} sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', px: 1.25, py: 0.75, justifyContent: 'flex-start', textAlign: 'left', borderRadius: '8px' }}>
        {open ? <ExpandMore sx={{ fontSize: 16 }} /> : <ChevronRight sx={{ fontSize: 16 }} />}
        <AccountTree sx={{ fontSize: 14, color: 'primary.main' }} />
        <Box component="span" sx={{ fontWeight: 600, flexShrink: 0 }}>Subagent</Box>
        <Box component="span" title={part.task} sx={{ color: 'text.secondary', flexGrow: 1, ...ellipsis }}>{part.task}</Box>
        {status}
      </ButtonBase>
      {open && part.tools.length > 0 && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75, pl: 3.5, pr: 1.25, pb: 1 }}>
          {part.tools.map((t) => (
            <ToolRow key={t.id} tool={t} />
          ))}
        </Box>
      )}
    </Box>
  )
}

/** A server the agent went without this turn, and why; the server's own output folds out when it left some. */
function Unavailable({ part }: { part: UnavailablePart }) {
  return (
    <Box sx={{ px: 1.25, py: 0.75, borderRadius: '8px', border: 1, borderColor: 'divider', fontSize: 13 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
        <ErrorOutlined sx={{ fontSize: 15, color: 'warning.main' }} />
        <span>
          <Box component="span" sx={{ fontFamily: MONO, fontSize: 12 }}>{part.server}</Box> was not available: {part.reason}.
        </span>
      </Box>
      {part.detail && (
        <Box component="details" sx={{ mt: 0.5, '& summary': { cursor: 'pointer', color: 'text.secondary', fontSize: 12 } }}>
          <summary>What the server said</summary>
          <Box component="pre" sx={{ m: 0, mt: 0.5, p: 1, borderRadius: '6px', bgcolor: 'var(--raised)', fontFamily: MONO, fontSize: 12, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 200, overflowY: 'auto' }}>
            {part.detail}
          </Box>
        </Box>
      )}
    </Box>
  )
}

function Plan({ items }: { items: PlanItem[] }) {
  return (
    <Box component="ul" aria-label="Plan" sx={{ m: 0, px: 1.25, py: 1, listStyle: 'none', border: 1, borderColor: 'divider', borderRadius: '8px', fontSize: 13, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
      {items.map((item, i) => (
        <Box component="li" key={i} sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
          {item.status === 'completed' ? (
            <CheckCircleOutline aria-label="Done" sx={{ fontSize: 16, mt: '2px', color: 'success.main' }} />
          ) : item.status === 'in_progress' ? (
            <ChevronRight aria-label="In progress" sx={{ fontSize: 16, mt: '2px', color: 'primary.main' }} />
          ) : (
            <RadioButtonUnchecked aria-label="To do" sx={{ fontSize: 16, mt: '2px', color: 'text.secondary' }} />
          )}
          <Box component="span" sx={{ color: item.status === 'completed' ? 'text.secondary' : 'text.primary', fontWeight: item.status === 'in_progress' ? 600 : 400 }}>{item.text}</Box>
        </Box>
      ))}
    </Box>
  )
}

type Props = {
  agentId: string
  /** The workspace, once loaded: its approval mode backs `/approvals`. */
  agent: Agent | null
  onAgent: (agent: Agent) => void
  /** The chat to open, or null for a new one. */
  chatId: string | null
  /** A message to send as soon as the models are known, once: the one typed on the home page. */
  initial?: string
  /** A new chat got its id: its first turn has started. */
  onChatId: (id: string) => void
  /** This chat does not exist (deleted, or never written to). */
  onMissing: () => void
  onTurnStart: () => void
  onTurnDone: () => void
  onTitle: (name: string) => void
  onOpen: (path: string) => void
  /** `/mcp`, whose state the workspace shares with its Name and purpose dialog. */
  mcp?: Command
}

// Waits between attempts to follow a turn again after the connection drops: quick at first, then
// every 10 s for as long as the page stays open, since the turn runs on the server either way.
const RETRY_MS = [1000, 2000, 5000, 10000]

const wait = (ms: number, signal: AbortSignal) =>
  new Promise<void>((done) => {
    const timer = setTimeout(done, ms)
    signal.addEventListener('abort', () => (clearTimeout(timer), done()), { once: true })
  })

export function Chat({ agentId, agent, onAgent, chatId: openedId, initial, onChatId, onMissing, onTurnStart, onTurnDone, onTitle, onOpen, mcp }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState<'loading' | string | null>(openedId ? 'loading' : null)
  const [more, setMore] = useState(false)
  const [loadingEarlier, setLoadingEarlier] = useState(false)
  const [running, setRunning] = useState(false)
  const [reconnecting, setReconnecting] = useState(false)
  const [notice, setNotice] = useState('')
  // Bumped to reopen the message box on a draft written for it.
  const [boxKey, setBoxKey] = useState(0)
  const models = useModelChoice()
  const approvals = useApprovalMode(agent, onAgent, setNotice)
  const commands = [...models.commands, approvals.command]
  const end = useRef<HTMLDivElement>(null)
  const sentInitial = useRef(false)
  const chatId = useRef(openedId)
  const turnId = useRef<string | null>(null)
  const firstTurnId = useRef<string | null>(null)
  // Aborted when the chat closes: only this page stops reading, the turn goes on.
  const alive = useRef(new AbortController())

  // A block body: scrollIntoView can return a promise, which React would take for a cleanup function.
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  const updateLast = (change: (m: AgentMessage) => Message) =>
    setMessages((all) => {
      const last = all.at(-1)
      return last?.role === 'agent' ? [...all.slice(0, -1), change(last)] : all
    })

  async function load(signal: AbortSignal) {
    if (!chatId.current) return
    setLoading('loading')
    try {
      const chat = await api<ChatDetail>(chatUrl(agentId, chatId.current), { signal })
      setMessages(fromTurns(chat.turns))
      setMore(chat.more)
      firstTurnId.current = chat.turns[0]?.id ?? null
      setLoading(null)
      const last = chat.turns.at(-1)
      if (last?.status === 'running') {
        turnId.current = last.id
        void follow(null, Date.parse(last.started_at))
      }
    } catch (e) {
      if (signal.aborted) return
      if (e instanceof ApiError && e.status === 404) onMissing()
      else setLoading(errorText(e))
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    alive.current = controller
    void load(controller.signal)
    return () => controller.abort()
    // Opened once per chat; the page gives each chat its own Chat.
  }, [])

  async function earlier() {
    if (!chatId.current || !firstTurnId.current) return
    setLoadingEarlier(true)
    try {
      const chat = await api<ChatDetail>(`${chatUrl(agentId, chatId.current)}?before=${firstTurnId.current}`)
      setMessages((all) => [...fromTurns(chat.turns), ...all])
      setMore(chat.more)
      firstTurnId.current = chat.turns[0]?.id ?? firstTurnId.current
    } catch (e) {
      setNotice(errorText(e))
    } finally {
      setLoadingEarlier(false)
    }
  }

  /** Reads a turn to its end: `first` is the stream that started it, or null to follow one already
   *  running. A dropped connection is followed again, and the turn's replay rebuilds the message,
   *  so nothing shown is lost or doubled. `started` hears whether a new turn began at all. */
  async function follow(first: AsyncGenerator<TurnEvent> | null, startedAt: number, started?: (ok: boolean) => void) {
    const signal = alive.current.signal
    let begun = !started
    let ended = false
    let attempt = 0
    setRunning(true)
    const finish = () => {
      if (ended) return
      ended = true
      updateLast((m) => ({ ...m, seconds: m.seconds ?? Math.round((Date.now() - startedAt) / 1000) }))
      setRunning(false)
      setReconnecting(false)
      // The agent may have changed files, so the explorer and open files catch up.
      onTurnDone()
    }
    for (;;) {
      try {
        const events = first ?? streamTurn(`${turnUrl(agentId, chatId.current!, turnId.current!)}/events`, undefined, signal)
        first = null
        for await (const event of events) {
          if (event.event === 'turn') {
            turnId.current = event.data.id
            // A rejoin replays the turn from its start, so the message is rebuilt from nothing.
            if (begun) updateLast(() => ({ role: 'agent', parts: [] }))
            else {
              begun = true
              started!(true)
              onTurnStart()
              if (chatId.current && !openedId) onChatId(chatId.current)
            }
            attempt = 0
            setReconnecting(false)
          } else if (event.event === 'title') onTitle(event.data.name)
          else updateLast((m) => apply(m, event))
          if (event.event === 'done' || event.event === 'error' || event.event === 'stopped') finish()
        }
        if (ended || signal.aborted) return
        // Closed with no ending: either the turn ended without one (the server restarted) or a
        // proxy cut a long stream. The stored chat says which.
        const chat = await api<ChatDetail>(chatUrl(agentId, chatId.current!), { signal })
        const turn = chat.turns.find((t) => t.id === turnId.current)
        if (turn?.status !== 'running') {
          updateLast((m) => ({ ...m, error: m.error ?? (turn?.status === 'interrupted' || !turn ? INTERRUPTED : undefined), stopped: m.stopped || turn?.status === 'stopped' }))
          finish()
          return
        }
      } catch (e) {
        if (signal.aborted) {
          if (!begun) started!(false)
          return
        }
        if (!begun) {
          // Nothing ran: the message goes back in the box, and only the reason stays here.
          setMessages((all) => all.slice(0, -2))
          setRunning(false)
          setNotice(errorText(e))
          started!(false)
          // Another tab is running a turn here: show it, so this tab follows it too.
          if (e instanceof ApiError && e.code === 'chat_busy') void load(signal)
          return
        }
        if (e instanceof ApiError && e.status === 404) {
          updateLast((m) => ({ ...m, error: 'This chat was deleted while the turn ran.' }))
          finish()
          return
        }
        setReconnecting(true)
      }
      await wait(RETRY_MS[Math.min(attempt++, RETRY_MS.length - 1)], signal)
      if (signal.aborted) return
    }
  }

  /** Resolves once the turn has started (true), or with false when it never did, so the message
   *  box gets the text back. The turn itself runs on after that. */
  async function send(prompt: string): Promise<boolean> {
    setNotice('')
    if (running) return false
    if (!models.choice) {
      setNotice('Choose a model with /model first.')
      return false
    }
    const choice = models.choice
    const signal = alive.current.signal
    setMessages((all) => [...all, { role: 'user', text: prompt }, { role: 'agent', parts: [] }])
    try {
      // Only an id: the chat is stored by the turn, so an unsent chat leaves nothing behind.
      chatId.current ??= (await api<{ id: string }>(chatsUrl(agentId), { method: 'POST', signal })).id
    } catch (e) {
      setMessages((all) => all.slice(0, -2))
      if (!signal.aborted) setNotice(errorText(e))
      return false
    }
    const body = { prompt, credential_id: choice.credentialId, model: choice.model, effort: models.effort }
    const stream = streamTurn(`${chatUrl(agentId, chatId.current)}/turns`, body, signal)
    return new Promise((started) => void follow(stream, Date.now(), started))
  }

  async function stop() {
    if (!chatId.current || !turnId.current) return
    try {
      // The turn's stream then ends with stopped, in this tab and any other following it.
      await api(`${turnUrl(agentId, chatId.current, turnId.current)}/stop`, { method: 'POST' })
    } catch (e) {
      setNotice(errorText(e))
    }
  }

  // The message typed on the home page, sent once the keys are known. It waits as this
  // workspace's draft until then, so a reload before it is sent keeps it in the box.
  useEffect(() => {
    if (!initial || sentInitial.current || models.keys === null) return
    sentInitial.current = true
    send(initial).then((ok) => {
      writeDraft(agentId, ok ? '' : initial)
      if (!ok) setBoxKey((k) => k + 1)
    })
    // send reads the latest state when called; this runs once, when the keys arrive.
  }, [initial, models.keys])

  return (
    <Box component="section" aria-label="Chat" sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' }}>
      <Box sx={{ flexGrow: 1, minHeight: 0, overflowY: 'auto' }}>
        <Box sx={{ maxWidth: 760, mx: 'auto', p: 2, display: 'flex', flexDirection: 'column', gap: 2, fontSize: 14, lineHeight: 1.55, minHeight: '100%' }}>
          {loading === 'loading' ? (
            <Box role="status" aria-label="Loading the chat" sx={{ m: 'auto' }}>
              <CircularProgress size={20} />
            </Box>
          ) : loading ? (
            <Alert severity="error" sx={{ m: 'auto' }} action={<Button size="small" onClick={() => void load(alive.current.signal)}>Retry</Button>}>
              The chat could not be loaded. {loading}
            </Alert>
          ) : (
            messages.length === 0 && (
              <Typography color="text.secondary" sx={{ m: 'auto', textAlign: 'center', maxWidth: 360 }}>
                Give the agent a task and correct it where needed. What it learns stays with this workspace.
              </Typography>
            )
          )}
          {more && !loading && (
            <Button size="small" onClick={earlier} disabled={loadingEarlier} sx={{ alignSelf: 'center' }}>
              {loadingEarlier ? 'Loading…' : 'Show earlier messages'}
            </Button>
          )}
          {messages.map((m, i) =>
            m.role === 'user' ? (
              <Box key={i} sx={{ alignSelf: 'flex-end', maxWidth: '85%', px: 1.75, py: 1.25, borderRadius: '12px 12px 4px 12px', bgcolor: 'var(--raised)', overflowWrap: 'anywhere' }}>
                <Markdown text={m.text} />
              </Box>
            ) : (
              <Box key={i} sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {m.parts.map((p, j) =>
                  p.kind === 'text' ? (
                    <Markdown key={j} text={p.text} />
                  ) : p.kind === 'tool' ? (
                    <ToolRow key={p.id} tool={p} />
                  ) : p.kind === 'approval' ? (
                    <ApprovalCard key={p.id} agentId={agentId} part={p} live={i === messages.length - 1 && running} />
                  ) : p.kind === 'unavailable' ? (
                    <Unavailable key={`mcp-${p.server}`} part={p} />
                  ) : p.kind === 'delegate' ? (
                    <DelegateBlock key={p.id} part={p} running={i === messages.length - 1 && !!running} />
                  ) : (
                    <Plan key="plan" items={p.items} />
                  ),
                )}
                {m.learned && m.learned.length > 0 && (
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 0.75, px: 1.25, py: 0.75, borderRadius: '8px', bgcolor: 'var(--accentSoft)', fontSize: 12 }}>
                    <AutoStories sx={{ fontSize: 14, color: 'primary.main' }} />
                    <span>Learned:</span>
                    {m.learned.map((name) => (
                      <Link key={name} component="button" type="button" onClick={() => onOpen(`.agent/skills/${name}/SKILL.md`)} sx={{ fontFamily: MONO, fontSize: 12 }}>
                        {name}
                      </Link>
                    ))}
                  </Box>
                )}
                {i === messages.length - 1 && running && (
                  <Typography role="status" color="text.secondary" sx={{ fontSize: 12 }}>
                    {reconnecting
                      ? 'Connection lost. Reconnecting… The agent keeps working meanwhile.'
                      : m.parts.some((p) => p.kind === 'approval' && !p.decision)
                        ? 'Waiting for your approval…'
                        : 'Working…'}
                  </Typography>
                )}
                {m.truncated && <Typography color="text.secondary" sx={{ fontSize: 12 }}>{TRUNCATED}</Typography>}
                {m.error && <Alert severity="error" sx={{ fontSize: 13 }}>{m.error}</Alert>}
                {m.stopped && (
                  <Typography color="text.secondary" sx={{ fontSize: 12 }}>
                    Stopped. What the agent already changed stays in its files.
                  </Typography>
                )}
                {(m.usage || m.seconds !== undefined) && !(i === messages.length - 1 && running) && (
                  <Typography color="text.secondary" sx={{ fontSize: 12 }}>
                    {m.usage && `${compact(m.usage.inputTokens + m.usage.cacheReadInputTokens + m.usage.cacheWriteInputTokens)} in · ${compact(m.usage.outputTokens)} out · `}
                    {m.seconds} s
                  </Typography>
                )}
              </Box>
            ),
          )}
          <div ref={end} />
        </Box>
      </Box>

      <Box sx={{ maxWidth: 760, width: '100%', mx: 'auto', px: 2, pb: 2, pt: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
        {notice && <Alert severity="error" onClose={() => setNotice('')}>{notice}</Alert>}
        <Composer
          key={boxKey}
          draftKey={agentId}
          autoFocus={!initial}
          busy={running}
          disabled={models.keys?.length === 0}
          onSend={send}
          onStop={stop}
          placeholder="Give the agent a task, or type / for commands"
          commands={mcp ? [...commands, mcp] : commands}
          footer={<SettingsLabel state={{ ...models, commands }} yolo={approvals.mode === 'yolo'} />}
        />
      </Box>
    </Box>
  )
}
