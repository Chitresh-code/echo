import type { TurnEvent } from '../api/stream'
import type { Usage } from '../api/types'

export type ChatSummary = { id: string; title: string; created_at: string; updated_at: string; running: boolean }
export type ChatList = { chats: ChatSummary[]; more: boolean }
export type TurnStatus = 'running' | 'done' | 'failed' | 'stopped' | 'interrupted'
export type StoredTurn = {
  id: string
  prompt: string
  model: string | null
  effort: string | null
  status: TurnStatus
  usage: Usage | null
  truncated: boolean
  started_at: string
  ended_at: string | null
  events: TurnEvent[]
}
export type ChatDetail = ChatSummary & { turns: StoredTurn[]; more: boolean }

export const chatsUrl = (agentId: string) => `/api/agents/${agentId}/chats`
export const chatUrl = (agentId: string, chatId: string) => `${chatsUrl(agentId)}/${chatId}`
export const turnUrl = (agentId: string, chatId: string, turnId: string) => `${chatUrl(agentId, chatId)}/turns/${turnId}`

export const INTERRUPTED = 'The server restarted during this turn, so it stopped. What the agent already changed stays in its files.'
export const TRUNCATED = 'This turn was too long to keep in full, so part of it is not shown.'

// Chats used to be remembered per tab under this key; read once so an open tab keeps its chat.
const OLD_KEY = (agentId: string) => `echo.chat.${agentId}`

export function takeOldChat(agentId: string): string | null {
  try {
    const id = sessionStorage.getItem(OLD_KEY(agentId))
    sessionStorage.removeItem(OLD_KEY(agentId))
    return id && /^[0-9a-f]{32}$/.test(id) ? id : null
  } catch {
    return null
  }
}

export const chatPath = (agentId: string, chatId: string | null) => (chatId ? `/w/${agentId}/c/${chatId}` : `/w/${agentId}`)

export function seconds(turn: StoredTurn): number | undefined {
  // Chats imported from before chats were stored have no real duration: their start and end are the same time.
  return turn.ended_at && turn.ended_at !== turn.started_at ? Math.max(0, Math.round((Date.parse(turn.ended_at) - Date.parse(turn.started_at)) / 1000)) : undefined
}
