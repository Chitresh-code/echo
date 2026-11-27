import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { routes } from '../routes'
import { click, fakeLayout, ok, refused, press, settle } from '../test/dom'

// The workspace page carries Monaco; the sidebar only needs to know which one is open.
vi.mock('../pages/Workspace', () => ({ default: () => <p>workspace page</p> }))


const agent = (id: string, name: string, used: string | null) => ({ id, name, job: '', created_at: '2026-11-01T00:00:00Z', last_used_at: used })
const OLD = agent('old', 'Old one', null)
const NEW = agent('new', 'Fresh one', '2026-11-26T00:00:00Z')

let calls: { method: string; url: string; body?: unknown }[]
let answer: (method: string, url: string) => Response | undefined
let root: Root
let host: HTMLElement
let router: ReturnType<typeof createMemoryRouter>

beforeEach(() => {
  calls = []
  answer = () => undefined
  fakeLayout()
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    calls.push({ method, url, body: init.body ? JSON.parse(init.body as string) : undefined })
    const own = answer(method, url)
    if (own) return own
    if (url === '/api/auth/me') return ok({ id: 'u', name: 'Ada Lovelace', email: 'ada@example.com' })
    if (url === '/api/agents') return ok([NEW, OLD])
    if (method === 'POST' && url === '/api/auth/logout') return ok({})
    return refused(404, 'not_found', 'Not found.')
  })
  localStorage.clear()
  sessionStorage.clear()
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

async function open(path: string) {
  router = createMemoryRouter(routes, { initialEntries: [path] })
  await act(async () => root.render(<RouterProvider router={router} />))
  await settle()
}

const recent = () => [...document.querySelectorAll('section[aria-labelledby="recent-heading"] li a')] as HTMLAnchorElement[]
const byText = (selector: string, text: string) => [...document.querySelectorAll(selector)].find((e) => e.textContent?.trim() === text) as HTMLElement
const byLabel = (label: string) => document.querySelector(`[aria-label="${label}"]`) as HTMLElement

const key = press

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function startRename(name: string) {
  await click(byLabel(`Options for ${name}`))
  await click(byText('[role="menuitem"]', 'Rename'))
  await settle()
  return byLabel('Workspace name') as HTMLInputElement
}

test('lists workspaces most recent first and marks the open one', async () => {
  await open('/w/old')
  expect(recent().map((a) => a.textContent)).toEqual(['Fresh one', 'Old one'])
  expect(recent()[1].getAttribute('aria-current')).toBe('page')
  expect(recent()[0].getAttribute('aria-current')).toBeNull()
})

test('a failed load says so and Retry loads again', async () => {
  let fail = true
  answer = (_, url) => (url === '/api/agents' && fail ? refused(500, 'internal', 'The server had a problem.') : undefined)
  await open('/')
  expect(document.body.textContent).toContain('Your workspaces did not load. The server had a problem.')
  fail = false
  await click(byText('button', 'Retry'))
  expect(recent().map((a) => a.textContent)).toEqual(['Fresh one', 'Old one'])
})

test('rename saves on Enter and cancels on Escape', async () => {
  answer = (method) => (method === 'PATCH' ? ok({ ...OLD, name: 'Renamed' }) : undefined)
  await open('/')
  let input = await startRename('Old one')
  await type(input, 'Renamed')
  await key(input, 'Enter')
  await settle()
  expect(calls.filter((c) => c.method === 'PATCH')).toEqual([{ method: 'PATCH', url: '/api/agents/old', body: { name: 'Renamed' } }])
  expect(recent().map((a) => a.textContent)).toContain('Renamed')

  input = await startRename('Fresh one')
  await type(input, 'Not this')
  await key(input, 'Escape')
  expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(1)
  expect(recent().map((a) => a.textContent)).toContain('Fresh one')
})

test('a refused rename puts the old name back and says why', async () => {
  answer = (method) => (method === 'PATCH' ? refused(422, 'invalid_request', 'The name is too long.') : undefined)
  await open('/')
  const input = await startRename('Old one')
  await type(input, 'Too long')
  await key(input, 'Enter')
  await settle()
  expect(recent().map((a) => a.textContent)).toContain('Old one')
  expect(document.body.textContent).toContain('Could not rename "Old one": The name is too long.')
})

test('delete asks first, and a busy workspace stays with the reason', async () => {
  answer = (method) => (method === 'DELETE' ? refused(409, 'agent_busy', 'This workspace has a turn in progress.') : undefined)
  await open('/')
  await click(byLabel('Options for Old one'))
  await click(byText('[role="menuitem"]', 'Delete'))
  expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  await click(byText('[role="dialog"] button', 'Delete'))
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain('This workspace has a turn in progress.')
  expect(recent().map((a) => a.textContent)).toContain('Old one')
})

test('deleting the open workspace goes home', async () => {
  answer = (method) => (method === 'DELETE' ? ok({}) : undefined)
  await open('/w/old')
  await click(byLabel('Options for Old one'))
  await click(byText('[role="menuitem"]', 'Delete'))
  await click(byText('[role="dialog"] button', 'Delete'))
  expect(router.state.location.pathname).toBe('/')
  expect(recent().map((a) => a.textContent)).toEqual(['Fresh one'])
})

test('an old agent link opens the workspace', async () => {
  await open('/agents/old')
  expect(router.state.location.pathname).toBe('/w/old')
})

test('signing out clears unsent drafts', async () => {
  sessionStorage.setItem('echo.draft.home', 'half a thought')
  sessionStorage.setItem('echo.other', 'kept')
  await open('/')
  await click(byText('button', 'Ada Lovelace'))
  await click(byText('[role="menuitem"]', 'Sign out'))
  expect(calls.some((c) => c.url === '/api/auth/logout')).toBe(true)
  expect(sessionStorage.getItem('echo.draft.home')).toBeNull()
  expect(sessionStorage.getItem('echo.other')).toBe('kept')
  expect(router.state.location.pathname).toBe('/signin')
})

test('the collapsed sidebar is remembered', async () => {
  await open('/')
  await click(byLabel('Collapse sidebar'))
  expect(localStorage.getItem('echo.sidebar')).toBe('collapsed')
  expect(recent()).toHaveLength(0)
  act(() => root.unmount())
  root = createRoot(host)
  await open('/')
  expect(byLabel('Expand sidebar')).toBeTruthy()
})
