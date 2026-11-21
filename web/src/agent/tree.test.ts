import { expect, test } from 'vitest'
import { buildRows, statusLetters } from './tree'

const entries = [
  { path: 'README.md', type: 'file' as const },
  { path: 'src', type: 'dir' as const },
  { path: 'src/b.py', type: 'file' as const },
  { path: 'src/a.py', type: 'file' as const },
  { path: 'src/lib', type: 'dir' as const },
  { path: 'src/lib/x.py', type: 'file' as const },
  { path: '.agent', type: 'dir' as const },
]
const letters = statusLetters([
  { path: 'src/a.py', index: ' ', worktree: 'M', original_path: null },
  { path: 'src/lib/x.py', index: '?', worktree: '?', original_path: null },
  { path: 'README.md', index: 'A', worktree: ' ', original_path: null },
])

test('status letters', () => {
  expect([...letters]).toEqual([['src/a.py', 'M'], ['src/lib/x.py', 'U'], ['README.md', 'A']])
})

test('collapsed folders hide their children, folders come first', () => {
  const rows = buildRows(entries, letters, new Set())
  expect(rows.map((r) => [r.path, r.depth, r.status])).toEqual([['.agent', 0, ''], ['src', 0, '•'], ['README.md', 0, 'A']])
})

test('expanded folders show their children sorted', () => {
  const rows = buildRows(entries, letters, new Set(['src']))
  expect(rows.map((r) => [r.name, r.depth, r.status])).toEqual([
    ['.agent', 0, ''], ['src', 0, '•'], ['lib', 1, '•'], ['a.py', 1, 'M'], ['b.py', 1, ''], ['README.md', 0, 'A'],
  ])
})
