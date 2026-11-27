import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { routes } from '../routes'
import { click, fakeLayout, messageBox, ok, press, refused, typeMessage } from '../test/dom'

vi.mock('./Workspace', () => ({ default: () => <p>workspace page</p> }))

const KEY = { id: 'k1', label: 'Mine', provider: 'anthropic', created_at: '2026-11-01T00:00:00Z' }
const CREATED = { id: 'w9', name: 'New workspace', job: '', created_at: '2026-11-27T00:00:00Z', last_used_at: null }

let calls: { method: string; url: string; body?: unknown }[]
let answer: (method: string, url: string) => Response | undefined
let keys: unknown[]
let root: Root
let host: HTMLElement
let router: ReturnType<typeof createMemoryRouter>

beforeEach(() => {
  calls = []
  answer = () => undefined
  keys = [KEY]
  fakeLayout()
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    calls.push({ method, url, body: init.body ? JSON.parse(init.body as string) : undefined })
    const own = answer(method, url)
    if (own) return own
    if (url === '/api/auth/me') return ok({ id: 'u', name: 'Ada Lovelace', email: 'ada@example.com' })
    if (url === '/api/agents') return method === 'POST' ? ok(CREATED) : ok([])
    if (url === '/api/credentials') return ok(keys)
    return refused(404, 'not_found', 'Not found.')
  })
  localStorage.clear()
  localStorage.setItem('echo.model', JSON.stringify({ credentialId: 'k1', model: 'claude-haiku-5-5' }))
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
}

const posts = () => calls.filter((c) => c.method === 'POST' && c.url === '/api/agents')

test('a message starts a new workspace and hands the message to it', async () => {
  await open('/')
  await typeMessage('fix the *flaky* test')
  await press(messageBox(), 'Enter')
  expect(posts()).toEqual([{ method: 'POST', url: '/api/agents', body: {} }])
  expect(router.state.location.pathname).toBe('/w/w9')
  expect(router.state.location.state).toEqual({ send: 'fix the *flaky* test' })
  // The sidebar has it before the workspace page loads anything.
  expect(document.querySelector('section[aria-labelledby="recent-heading"] a[href="/w/w9"]')).toBeTruthy()
})

test('at the workspace limit it says why and keeps the message', async () => {
  answer = (method, url) =>
    method === 'POST' && url === '/api/agents'
      ? refused(409, 'agent_limit_reached', 'You have 50 workspaces, the most allowed. Delete one to start another.')
      : undefined
  await open('/')
  await typeMessage('keep this')
  await press(messageBox(), 'Enter')
  expect(router.state.location.pathname).toBe('/')
  expect(document.body.textContent).toContain('You have 50 workspaces, the most allowed. Delete one to start another.')
  expect(messageBox().editor.getMarkdown()).toBe('keep this')
})

test('with no model key the box is off and points to Credentials', async () => {
  keys = []
  await open('/')
  expect(messageBox().getAttribute('contenteditable')).toBe('false')
  const link = [...document.querySelectorAll('main a')].find((a) => a.textContent === 'Add a key') as HTMLAnchorElement
  expect(link.getAttribute('href')).toBe('/credentials')
  expect(document.querySelector('[aria-label^="Model "]')).toBeNull()
})

test('with keys but no model chosen it asks for one and keeps the message', async () => {
  localStorage.removeItem('echo.model')
  await open('/')
  await typeMessage('hello')
  await press(messageBox(), 'Enter')
  expect(posts()).toEqual([])
  expect(document.body.textContent).toContain('Choose a model with /model first.')
  expect(messageBox().editor.getMarkdown()).toBe('hello')
})

test('the draft is kept across a trip to Credentials', async () => {
  await open('/')
  await typeMessage('half a thought')
  await click([...document.querySelectorAll('nav a, aside a')].find((a) => a.textContent?.includes('Credentials')) as HTMLElement)
  expect(router.state.location.pathname).toBe('/credentials')
  await act(async () => router.navigate('/'))
  expect(messageBox().editor.getMarkdown()).toBe('half a thought')
})
