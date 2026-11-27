/** ask: the agent waits for the user before a tool that changes something; yolo: every call runs. */
export type ApprovalMode = 'ask' | 'yolo'
export type Agent = { id: string; name: string; job: string; created_at: string; last_used_at: string | null; approval_mode: ApprovalMode }
export type ApprovalDecision = 'allow' | 'deny' | 'always'
export type User = { id: string; name: string | null; email: string | null }
export type Provider = 'anthropic' | 'openai' | 'google' | 'openai_compatible'
export type Credential = { id: string; provider: Provider; label: string; base_url: string | null; key_hint: string; models: string[] | null; created_at: string }
export type ProviderModel = { id: string; name: string }
export type TreeEntry = { path: string; type: 'file' | 'dir' | 'link' | 'other' }
export type Tree = { entries: TreeEntry[]; truncated: boolean }
export type FileContent = { content: string; encoding: 'utf-8' | 'base64' }
export type AgentFile = FileContent & { path: string }
export type GitFileStatus = { path: string; index: string; worktree: string; original_path: string | null }
export type GitFileVersions = { head: FileContent | null; working: FileContent | null }
export type Usage = {
  inputTokens: number
  outputTokens: number
  cacheReadInputTokens: number
  cacheWriteInputTokens: number
  /** Estimated cost in millionths of a dollar; null when no call had a known price, absent on turns from before costs were counted. */
  costMicros?: number | null
  /** True when some calls had no known price, so the cost leaves them out. */
  unpriced?: boolean
}

/** One workspace, model or key's part of a usage period. */
export type UsageShare = { id: string; name: string | null; provider: string | null; cost_micros: number; tokens: number; turns: number; unpriced_tokens: number }

export type UsageReport = {
  totals: { cost_micros: number; input_tokens: number; output_tokens: number; cache_read_tokens: number; cache_write_tokens: number; turns: number; unpriced_tokens: number }
  days: { date: string; cost_micros: number; tokens: number }[]
  workspaces: UsageShare[]
  models: UsageShare[]
  keys: UsageShare[]
  prices: { source: string; fetched: string }
  since: string | null
}
export type Effort = 'auto' | 'off' | 'low' | 'medium' | 'high'

export const PROVIDERS: Record<Provider, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  google: 'Google',
  openai_compatible: 'OpenAI-compatible',
}
export type Skill = { name: string; description: string; path: string; status: 'ok' | 'warning' | 'skipped'; problem: string | null }
export type Skills = { skills: Skill[]; truncated: boolean }
export type Storage = { used_bytes: number; limit_bytes: number }
export type Note = { name: string; text: string; updated_at: string }
export type Process = { name: string; command: string; cwd: string | null; status: 'running' | 'exited'; exit_code: number | null; started_at: number }
export type Processes = { processes: Process[]; ports: number[] }
export type ProcessLog = { name: string; log: string }
export type McpStatus = 'ok' | 'needs_auth' | 'needs_scope' | 'tools_changed'
export type McpTool = { name: string; description: string; hints: Record<string, unknown> | null }
/** A server as the API shows it: the names of its headers and variables, never their values. */
export type McpServer = {
  id: string
  name: string
  kind: 'remote' | 'local'
  url: string | null
  auth: 'none' | 'headers' | 'oauth' | null
  command: string | null
  args: string[] | null
  header_names: string[]
  env_names: string[]
  preregistered: boolean
  status: McpStatus
  tools: McpTool[]
  pending_tools: McpTool[] | null
  pending_hash: string | null
  created_at: string
}
