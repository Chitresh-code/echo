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
