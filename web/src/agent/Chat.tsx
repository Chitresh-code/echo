import AccountTree from '@mui/icons-material/AccountTree'
import AutoStories from '@mui/icons-material/AutoStories'
import CheckCircleOutline from '@mui/icons-material/CheckCircleOutlineOutlined'
import ChevronRight from '@mui/icons-material/ChevronRight'
import ErrorOutlined from '@mui/icons-material/ErrorOutlined'
import ExpandMore from '@mui/icons-material/ExpandMore'
import RadioButtonUnchecked from '@mui/icons-material/RadioButtonUnchecked'
import Terminal from '@mui/icons-material/Terminal'
import { Alert, Box, ButtonBase, CircularProgress, Link, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client'
import { streamTurn, type PlanItem, type TurnEvent } from '../api/stream'
import type { Usage } from '../api/types'
import { compact } from '../format'
import { MONO } from '../theme'
import { Composer, writeDraft } from '../composer/Composer'
import { Markdown } from './Markdown'
import { SettingsLabel } from '../composer/SettingsLabel'
import { useModelChoice } from './modelChoice'

// ok is missing until the call's result arrives.
type ToolPart = { kind: 'tool'; id: string; name: string; skill?: string; detail?: string; ok?: boolean }
// A subagent, in place of the subagent call that started it.
type DelegatePart = { kind: 'delegate'; id: string; task: string; tools: ToolPart[]; ok?: boolean }
type Part = { kind: 'text'; text: string } | ToolPart | DelegatePart | { kind: 'plan'; items: PlanItem[] }
type Message =
  | { role: 'user'; text: string }
  | { role: 'agent'; parts: Part[]; usage?: Usage; learned?: string[]; seconds?: number; error?: string; stopped?: boolean }
type AgentMessage = Extract<Message, { role: 'agent' }>

// shortcut: per tab and not shared, so two tabs on one workspace hold separate chats and neither sees the other's turn; coordinate through stored chats.
const chatKey = (agentId: string) => `echo.chat.${agentId}`

function storedChat(agentId: string): string | null {
  try {
    return sessionStorage.getItem(chatKey(agentId))
  } catch {
    return null
  }
}

export function storeChat(agentId: string, chatId: string | null) {
  try {
    if (chatId) sessionStorage.setItem(chatKey(agentId), chatId)
    else sessionStorage.removeItem(chatKey(agentId))
  } catch {
    // Without storage a reload starts a new chat.
  }
}

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
    case 'done':
      return { ...message, usage: event.data.usage, learned: event.data.learned }
    case 'error':
      return { ...message, error: event.data.request_id ? `${event.data.message} (request ${event.data.request_id})` : event.data.message }
    case 'title':
      return message
  }
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
  /** A message to send as soon as the models are known, once: the one typed on the home page. */
  initial?: string
  onTurnStart: () => void
  onTurnDone: () => void
  onTitle: (name: string) => void
  /** Stops the running turn; null when none runs. */
  onRunning: (stop: (() => void) | null) => void
  onOpen: (path: string) => void
}

export function Chat({ agentId, initial, onTurnStart, onTurnDone, onTitle, onRunning, onOpen }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [chatId, setChatId] = useState<string | null>(() => storedChat(agentId))
  const [running, setRunning] = useState<AbortController | null>(null)
  const [notice, setNotice] = useState('')
  // Bumped to reopen the message box on a draft written for it.
  const [boxKey, setBoxKey] = useState(0)
  const models = useModelChoice()
  const end = useRef<HTMLDivElement>(null)
  const sentInitial = useRef(false)

  // A block body: scrollIntoView can return a promise, which React would take for a cleanup function.
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  useEffect(() => onRunning(running ? () => running.abort() : null), [running, onRunning])

  const updateLast = (change: (m: AgentMessage) => Message) =>
    setMessages((all) => {
      const last = all.at(-1)
      return last?.role === 'agent' ? [...all.slice(0, -1), change(last)] : all
    })

  /** Resolves once the turn has started (true), or with false when it never did, so the message
   *  box gets the text back. The turn itself runs on after that. */
  function send(prompt: string): Promise<boolean> {
    setNotice('')
    if (running) return Promise.resolve(false)
    if (!models.choice) {
      setNotice('Choose a model with /model first.')
      return Promise.resolve(false)
    }
    const choice = models.choice
    return new Promise((started) => void run(prompt, choice, started))
  }

  async function run(prompt: string, choice: NonNullable<typeof models.choice>, started: (ok: boolean) => void) {
    setMessages((all) => [...all, { role: 'user', text: prompt }, { role: 'agent', parts: [] }])
    const controller = new AbortController()
    setRunning(controller)
    const startedAt = performance.now()
    let begun = false
    let finished = false
    // The reply ends at done; the stream can stay open a little longer for the workspace's title.
    const finish = () => {
      if (finished) return
      finished = true
      const seconds = Math.round((performance.now() - startedAt) / 1000)
      updateLast((m) => ({ ...m, seconds }))
      setRunning(null)
      // The agent may have changed files, so the explorer and open files catch up.
      onTurnDone()
    }
    try {
      let id = chatId
      if (!id) {
        id = (await api<{ id: string }>(`/api/agents/${agentId}/chats`, { method: 'POST' })).id
        setChatId(id)
        storeChat(agentId, id)
      }
      const body = { prompt, credential_id: choice.credentialId, model: choice.model, effort: models.effort }
      for await (const event of streamTurn(`/api/agents/${agentId}/chats/${id}/turns`, body, controller.signal)) {
        if (!begun) {
          begun = true
          started(true)
          onTurnStart()
        }
        if (event.event === 'title') onTitle(event.data.name)
        else updateLast((m) => apply(m, event))
        if (event.event === 'done' || event.event === 'error') finish()
      }
    } catch (e) {
      if (!begun) {
        // Nothing ran: the message goes back in the box, and only the reason stays here.
        setMessages((all) => all.slice(0, -2))
        setRunning(null)
        if (!controller.signal.aborted) setNotice(errorText(e))
        finished = true
        started(false)
        return
      }
      if (!finished) {
        if (controller.signal.aborted) updateLast((m) => ({ ...m, stopped: true }))
        else updateLast((m) => ({ ...m, error: `${errorText(e)} The connection to the agent was lost, so the turn stopped. What it already changed stays in its files.` }))
      }
    } finally {
      if (!begun) started(true)
      finish()
    }
  }

  // The message typed on the home page, sent once the keys are known. If it cannot be sent it is
  // left in the box as a draft instead of being lost.
  useEffect(() => {
    if (!initial || sentInitial.current || models.keys === null) return
    sentInitial.current = true
    send(initial).then((ok) => {
      if (ok) return
      writeDraft(agentId, initial)
      setBoxKey((k) => k + 1)
    })
    // send reads the latest state when called; this runs once, when the keys arrive.
  }, [initial, models.keys])

  return (
    <Box component="section" aria-label="Chat" sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' }}>
      <Box sx={{ flexGrow: 1, minHeight: 0, overflowY: 'auto' }}>
        <Box sx={{ maxWidth: 760, mx: 'auto', p: 2, display: 'flex', flexDirection: 'column', gap: 2, fontSize: 14, lineHeight: 1.55, minHeight: '100%' }}>
          {messages.length === 0 && (
            <Typography color="text.secondary" sx={{ m: 'auto', textAlign: 'center', maxWidth: 360 }}>
              {chatId
                ? 'This chat continues where it left off. Earlier messages are not shown after a reload.'
                : 'Give the agent a task and correct it where needed. What it learns stays with this workspace.'}
            </Typography>
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
                {i === messages.length - 1 && running && <Typography role="status" color="text.secondary" sx={{ fontSize: 12 }}>Working…</Typography>}
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
          busy={!!running}
          disabled={models.keys?.length === 0}
          onSend={send}
          onStop={() => running?.abort()}
          placeholder="Give the agent a task, or type / for commands"
          commands={models.commands}
          footer={<SettingsLabel state={models} />}
        />
      </Box>
    </Box>
  )
}
