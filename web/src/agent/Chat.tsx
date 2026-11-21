import AddComment from '@mui/icons-material/AddComment'
import ArrowUpward from '@mui/icons-material/ArrowUpward'
import Stop from '@mui/icons-material/Stop'
import Terminal from '@mui/icons-material/Terminal'
import { Alert, Box, IconButton, InputBase, Tooltip, Typography } from '@mui/material'
import { useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client'
import { streamTurn, type TurnEvent } from '../api/stream'
import type { Usage } from '../api/types'
import { compact } from '../format'
import { MONO } from '../theme'
import { Markdown } from './Markdown'
import { ModelPicker, useModelChoice } from './ModelPicker'

type Part = { kind: 'text'; text: string } | { kind: 'tool'; id: string; name: string }
type Message =
  | { role: 'user'; text: string }
  | { role: 'agent'; parts: Part[]; usage?: Usage; seconds?: number; error?: string; stopped?: boolean }

const chatKey = (agentId: string) => `echo.chat.${agentId}`

function storedChat(agentId: string): string | null {
  try {
    return sessionStorage.getItem(chatKey(agentId))
  } catch {
    return null
  }
}

function storeChat(agentId: string, chatId: string | null) {
  try {
    if (chatId) sessionStorage.setItem(chatKey(agentId), chatId)
    else sessionStorage.removeItem(chatKey(agentId))
  } catch {
    // Without storage a reload starts a new chat.
  }
}

/** Adds one stream event to the agent's message: text joins the text before it, each tool gets a row. */
function apply(message: Extract<Message, { role: 'agent' }>, event: TurnEvent): Message {
  const parts = [...message.parts]
  const last = parts.at(-1)
  switch (event.event) {
    case 'text':
      if (last?.kind === 'text') parts[parts.length - 1] = { ...last, text: last.text + event.data.text }
      else parts.push({ kind: 'text', text: event.data.text })
      return { ...message, parts }
    case 'tool':
      return { ...message, parts: [...parts, { kind: 'tool' as const, id: event.data.id, name: event.data.name }] }
    case 'done':
      return { ...message, usage: event.data.usage }
    case 'error':
      return { ...message, error: `${event.data.message} (${event.data.code}${event.data.request_id ? `, request ${event.data.request_id}` : ''})` }
  }
}

export function Chat({ agentId, onTurnDone }: { agentId: string; onTurnDone: () => void }) {
  const [messages, setMessages] = useState<Message[]>([])
  const [chatId, setChatId] = useState<string | null>(() => storedChat(agentId))
  const [draft, setDraft] = useState('')
  const [running, setRunning] = useState<AbortController | null>(null)
  const models = useModelChoice()
  const end = useRef<HTMLDivElement>(null)

  // A block body: scrollIntoView can return a promise, which React would take for a cleanup function.
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  const updateLast = (change: (m: Extract<Message, { role: 'agent' }>) => Message) =>
    setMessages((all) => {
      const last = all.at(-1)
      return last?.role === 'agent' ? [...all.slice(0, -1), change(last)] : all
    })

  async function send() {
    const prompt = draft.trim()
    if (!prompt || running || !models.choice) return
    setDraft('')
    setMessages((all) => [...all, { role: 'user', text: prompt }, { role: 'agent', parts: [] }])
    const controller = new AbortController()
    setRunning(controller)
    const started = performance.now()
    try {
      let id = chatId
      if (!id) {
        id = (await api<{ id: string }>(`/api/agents/${agentId}/chats`, { method: 'POST' })).id
        setChatId(id)
        storeChat(agentId, id)
      }
      const body = { prompt, credential_id: models.choice.credentialId, model: models.choice.model, effort: models.effort }
      for await (const event of streamTurn(`/api/agents/${agentId}/chats/${id}/turns`, body, controller.signal)) {
        updateLast((m) => apply(m, event))
      }
    } catch (e) {
      if (controller.signal.aborted) updateLast((m) => ({ ...m, stopped: true }))
      else updateLast((m) => ({ ...m, error: errorText(e) }))
    } finally {
      const seconds = Math.round((performance.now() - started) / 1000)
      updateLast((m) => ({ ...m, seconds }))
      setRunning(null)
      // The agent may have changed files, so the explorer and open files catch up.
      onTurnDone()
    }
  }

  function newChat() {
    setChatId(null)
    storeChat(agentId, null)
    setMessages([])
  }

  const title = messages.find((m) => m.role === 'user')?.text ?? (chatId ? 'Chat' : 'New chat')

  return (
    <Box component="section" aria-label="Chat" sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%', bgcolor: 'background.paper' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 1, pl: 2, pr: 1, borderBottom: 1, borderColor: 'divider' }}>
        <Typography sx={{ flexGrow: 1, minWidth: 0, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</Typography>
        <Tooltip title="New chat">
          <span>
            <IconButton aria-label="New chat" onClick={newChat} disabled={!!running} sx={{ width: 32, height: 32, border: 1, borderColor: 'divider', borderRadius: '8px' }}>
              <AddComment sx={{ fontSize: 16 }} />
            </IconButton>
          </span>
        </Tooltip>
      </Box>

      <Box sx={{ flexGrow: 1, overflowY: 'auto', p: 2, display: 'flex', flexDirection: 'column', gap: 2, fontSize: 14, lineHeight: 1.55 }}>
        {messages.length === 0 && (
          <Typography color="text.secondary" sx={{ m: 'auto', textAlign: 'center', maxWidth: 300 }}>
            {chatId
              ? 'This chat continues where it left off. Earlier messages are not shown after a reload.'
              : 'Show the agent its job: give it a task, then correct it. What it learns stays with this agent.'}
          </Typography>
        )}
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <Box key={i} sx={{ alignSelf: 'flex-end', maxWidth: '85%', px: 1.75, py: 1.25, borderRadius: '12px 12px 4px 12px', bgcolor: 'var(--raised)', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
              {m.text}
            </Box>
          ) : (
            <Box key={i} sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {m.parts.map((p, j) =>
                p.kind === 'text' ? (
                  <Markdown key={j} text={p.text} />
                ) : (
                  <Box key={p.id} sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.25, py: 0.75, border: 1, borderColor: 'divider', borderRadius: '8px', bgcolor: 'background.default', fontSize: 12 }}>
                    <Terminal sx={{ fontSize: 14, color: 'text.secondary' }} />
                    <Box component="span" sx={{ fontFamily: MONO, color: 'text.secondary', fontWeight: 600 }}>{p.name}</Box>
                  </Box>
                ),
              )}
              {i === messages.length - 1 && running && <Typography color="text.secondary" sx={{ fontSize: 12 }}>Working…</Typography>}
              {m.error && <Alert severity="error" sx={{ fontSize: 13 }}>{m.error}</Alert>}
              {m.stopped && (
                <Typography color="text.secondary" sx={{ fontSize: 12 }}>
                  Stopped watching. The agent finishes this turn on the server; its result shows in the files.
                </Typography>
              )}
              {(m.usage || m.seconds !== undefined) && !running && (
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

      <Box
        component="form"
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
        sx={{ pt: 1.5, px: 2, pb: 2, borderTop: 1, borderColor: 'divider', display: 'flex', flexDirection: 'column', gap: 1 }}
      >
        <InputBase
          multiline
          minRows={3}
          maxRows={12}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              send()
            }
          }}
          placeholder="Give the agent a task, or correct what it did"
          inputProps={{ 'aria-label': 'Message the agent', maxLength: 100000 }}
          sx={{ px: 1.5, py: 1.25, border: 1, borderColor: 'divider', borderRadius: '10px', bgcolor: 'background.default' }}
        />
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0, '& > button:last-of-type': { flexShrink: 0 } }}>
          <ModelPicker state={models} disabled={!!running} />
          <Box sx={{ flexGrow: 1 }} />
          {running ? (
            <IconButton aria-label="Stop" onClick={() => running.abort()} sx={{ width: 36, height: 36, borderRadius: '10px', border: 1, borderColor: 'divider' }}>
              <Stop fontSize="small" />
            </IconButton>
          ) : (
            <IconButton
              type="submit"
              aria-label="Send"
              disabled={!draft.trim() || !models.choice}
              sx={{ width: 36, height: 36, borderRadius: '10px', bgcolor: 'primary.main', color: 'primary.contrastText', '&:hover': { bgcolor: 'primary.dark' }, '&.Mui-disabled': { bgcolor: 'var(--raised)' } }}
            >
              <ArrowUpward fontSize="small" />
            </IconButton>
          )}
        </Box>
      </Box>
    </Box>
  )
}
