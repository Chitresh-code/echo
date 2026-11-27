import type { GitFileStatus, TreeEntry } from '../api/types'

export type Row = { path: string; name: string; depth: number; dir: boolean; status: string }

/** One letter per changed path, as the explorer shows it: U for untracked, else the working tree's
 *  letter, else the index's. */
export function statusLetters(statuses: GitFileStatus[]): Map<string, string> {
  const letters = new Map<string, string>()
  for (const s of statuses) {
    const letter = s.index === '?' ? 'U' : s.worktree.trim() || s.index.trim()
    if (letter) letters.set(s.path, letter)
  }
  return letters
}

/** The visible rows of the file tree: folders first, then files, each sorted by name, and only the
 *  children of expanded folders. A folder holding changed files gets a dot. */
export function buildRows(entries: TreeEntry[], letters: Map<string, string>, expanded: Set<string>): Row[] {
  const children = new Map<string, TreeEntry[]>()
  for (const entry of entries) {
    const slash = entry.path.lastIndexOf('/')
    const parent = slash < 0 ? '' : entry.path.slice(0, slash)
    if (!children.has(parent)) children.set(parent, [])
    children.get(parent)!.push(entry)
  }
  const changed = [...letters.keys()]
  const rows: Row[] = []
  const walk = (parent: string, depth: number) => {
    const list = [...(children.get(parent) ?? [])].sort(
      (a, b) => Number(b.type === 'dir') - Number(a.type === 'dir') || a.path.localeCompare(b.path),
    )
    for (const entry of list) {
      const dir = entry.type === 'dir'
      const status = dir ? (changed.some((p) => p.startsWith(`${entry.path}/`)) ? '•' : '') : (letters.get(entry.path) ?? '')
      rows.push({ path: entry.path, name: entry.path.slice(entry.path.lastIndexOf('/') + 1), depth, dir, status })
      if (dir && expanded.has(entry.path)) walk(entry.path, depth + 1)
    }
  }
  walk('', 0)
  return rows
}

/** Why a name typed in the explorer cannot be made inside `folder`, or null when it can. Slashes
 *  make folders on the way, so `lib/a.ts` is fine; every folder on the way must not be a file. */
export function nameProblem(name: string, entries: TreeEntry[], folder: string): string | null {
  const typed = name.trim()
  if (!typed) return 'Type a name.'
  if (typed.startsWith('/')) return 'A name cannot start with /.'
  if (typed.includes('\\')) return 'Use / to separate folders.'
  if (/[\u0000-\u001f]/.test(typed)) return 'The name has a character a file name cannot hold.'
  const parts = typed.replace(/\/+$/, '').split('/')
  if (parts.some((p) => p === '' || p === '.' || p === '..')) return 'Each part of the name must be a real name, not empty, . or ..'
  if (parts.some((p) => new TextEncoder().encode(p).length > 255)) return 'The name is too long.'
  const kinds = new Map(entries.map((e) => [e.path, e.type]))
  let path = folder
  for (const [i, part] of parts.entries()) {
    path = path ? `${path}/${part}` : part
    const kind = kinds.get(path)
    if (i === parts.length - 1 && kind) return `${part} already exists here. Pick another name.`
    if (kind && kind !== 'dir') return `${part} is a file, so it cannot hold others.`
  }
  return null
}

/** The folders that hold `path`, outermost first: ['a', 'a/b'] for a/b/c. */
export function parents(path: string): string[] {
  const parts = path.split('/')
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join('/'))
}
