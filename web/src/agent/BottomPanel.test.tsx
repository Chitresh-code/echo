import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ok, refused } from '../test/dom'
import { BottomPanel } from './BottomPanel'

// The terminal itself needs a real canvas and socket; here it is a stand-in that names its shell.
vi.mock('./Terminal', () => ({ Terminal: ({ id }: { id: string }) => <div data-shell={id} /> }))

let calls: { method: string; url: string }[]
let listed: { id: string; started_at: number }[]
let startAnswer: () => Response
let root: Root
let host: HTMLElement

beforeEach(() => {
  calls = []
  listed = []
  startAnswer = () => ok({ id: 'b'.repeat(32), started_at: 2, attached: 0 })
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    calls.push({ method, url })
    if (url.endsWith('/terminals') && method === 'GET') return ok({ terminals: listed })
    if (url.endsWith('/terminals') && method === 'POST') return startAnswer()
    if (method === 'DELETE') return ok({ deleted: true })
    return refused(404, 'not_found', 'No.')
  })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
})

const flush = () => act(async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0)) })
const tabs = () => [...host.querySelectorAll('[role="tab"]')].map((t) => t.textContent)
const shells = () => [...host.querySelectorAll('[data-shell]')].map((t) => t.getAttribute('data-shell'))
const posts = () => calls.filter((c) => c.method === 'POST').length

test('opening lists the running shells and starts none', async () => {
  listed = [{ id: 'a'.repeat(32), started_at: 1 }]
  act(() => root.render(<BottomPanel agentId="ag" open onClose={() => {}} />))
  await flush()
  expect(tabs()).toEqual(['Terminal 1'])
  expect(shells()).toEqual(['a'.repeat(32)])
  expect(posts()).toBe(0)
})

test('opening with no shell starts one, and the plus starts another', async () => {
  act(() => root.render(<BottomPanel agentId="ag" open onClose={() => {}} />))
  await flush()
  expect(posts()).toBe(1)
  expect(tabs()).toEqual(['Terminal 1'])
  startAnswer = () => ok({ id: 'c'.repeat(32), started_at: 3, attached: 0 })
  await act(async () => (host.querySelector('button[aria-label="New terminal"]') as HTMLElement).click())
  await flush()
  expect(tabs()).toEqual(['Terminal 1', 'Terminal 2'])
  // Closing a tab ends its shell on the server.
  await act(async () => (host.querySelector('[aria-label="Close terminal 2"]') as HTMLElement).click())
  await flush()
  expect(tabs()).toEqual(['Terminal 1'])
  expect(calls.some((c) => c.method === 'DELETE' && c.url.endsWith('c'.repeat(32)))).toBe(true)
})

test('a refused start shows why', async () => {
  startAnswer = () => refused(409, 'too_many_terminals', 'A workspace can have at most 4 terminals open; close one first.')
  act(() => root.render(<BottomPanel agentId="ag" open onClose={() => {}} />))
  await flush()
  expect(host.textContent).toContain('at most 4 terminals')
})

test('a closed panel asks the server nothing', async () => {
  act(() => root.render(<BottomPanel agentId="ag" open={false} onClose={() => {}} />))
  await flush()
  expect(calls).toEqual([])
})
