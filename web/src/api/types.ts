export type Agent = { id: string; name: string; job: string; created_at: string; last_used_at: string | null }
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
export type Usage = { inputTokens: number; outputTokens: number; cacheReadInputTokens: number; cacheWriteInputTokens: number }
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
