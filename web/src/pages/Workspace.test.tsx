import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { routes } from '../routes'
import { click, fakeLayout, messageBox, ok, press, refused, settle, typeMessage } from '../test/dom'

// Loaded before the tests, so the lazy route is ready on first render.
await import('./Workspace')

// Monaco does not run in jsdom; the panel only needs something in the editor's place.
vi.mock('../agent/Editor', () => ({ Editor: () => <p>editor</p> }))

const KEY = { id: 'k1', label: 'Mine', provider: 'anthropic', created_at: '2026-11-01T00:00:00Z' }
const ws = (name: string, used: string | null = null) => ({ id: 'w9', name, job: '', created_at: '2026-11-27T00:00:00Z', last_used_at: used })
const usage = { inputTokens: 10, outputTokens: 5, cacheReadInputTokens: 0, cacheWriteInputTokens: 0 }

/** A turn's event stream that the test writes to, and that ends when the page aborts the request. */
function turnStream(signal?: AbortSignal | null) {
  let ctl!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({ start: (c) => void (ctl = c) })
  const turn = {
    aborted: false,
    response: new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }),
    send: (event: string, data: unknown) => ctl.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)),
    close: () => ctl.close(),
  }
  signal?.addEventListener('abort', () => {
    turn.aborted = true
    ctl.error(new DOMException('The request was stopped.', 'AbortError'))
  })
  return turn
}

let calls: { method: string; url: string; body?: unknown }[]
let workspace: ReturnType<typeof ws>
let turns: ReturnType<typeof turnStream>[]
let refuseTurn: Response | null
let root: Root
let host: HTMLElement
let router: ReturnType<typeof createMemoryRouter>

beforeEach(() => {
  calls = []
  turns = []
  refuseTurn = null
  workspace = ws('New workspace')
  fakeLayout()
  Element.prototype.scrollIntoView = () => {}
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    calls.push({ method, url, body: init.body ? JSON.parse(init.body as string) : undefined })
    if (url === '/api/auth/me') return ok({ id: 'u', name: 'Ada Lovelace', email: 'ada@example.com' })
    if (url === '/api/agents') return method === 'POST' ? ok(workspace) : ok([workspace])
    if (url === '/api/agents/w9') return ok(workspace)
    if (url === '/api/agents/gone') return refused(404, 'not_found', 'This workspace does not exist.')
    if (url === '/api/credentials') return ok([KEY])
    if (url.endsWith('/tree')) return ok({ entries: [], truncated: false })
    if (url.endsWith('/git/status')) return ok([])
    if (url.endsWith('/chats')) return ok({ id: 'c1' })
    if (url.endsWith('/turns')) {
      if (refuseTurn) return refuseTurn
      const turn = turnStream(init.signal)
      turns.push(turn)
      return turn.response
    }
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

async function open(path: string, state?: unknown) {
  router = createMemoryRouter(routes, { initialEntries: [{ pathname: path, state }] })
  await act(async () => root.render(<RouterProvider router={router} />))
  await settle()
}

const turnPosts = () => calls.filter((c) => c.url.endsWith('/turns'))
const heading = () => document.querySelector('main h1')?.textContent
const sidebarNames = () => [...document.querySelectorAll('section[aria-labelledby="recent-heading"] li a')].map((a) => a.textContent)
const byText = (selector: string, text: string) => [...document.querySelectorAll(selector)].find((e) => e.textContent?.trim() === text) as HTMLElement
const byLabel = (label: string) => document.querySelector(`[aria-label="${label}"]`) as HTMLElement

test('the message from home is sent once, and not again after a reload', async () => {
  await open('/')
  await typeMessage('fix the *flaky* test')
  await press(messageBox(), 'Enter')
  await settle()
  expect(router.state.location.pathname).toBe('/w/w9')
  expect(turnPosts()).toHaveLength(1)
  expect(turnPosts()[0].body).toMatchObject({ prompt: 'fix the *flaky* test', credential_id: 'k1', model: 'claude-haiku-5-5' })
  // The history entry no longer carries it.
  expect(router.state.location.state).toBeNull()
  turns[0].send('done', { stopReason: 'end_turn', usage })
  turns[0].close()
  await settle()

  act(() => root.unmount())
  root = createRoot(host)
  await open('/w/w9', router.state.location.state)
  expect(turnPosts()).toHaveLength(1)
})

test('the title renames the header and the sidebar, even after done', async () => {
  await open('/w/w9')
  expect(heading()).toBe('New workspace')
  workspace = ws('fix the flaky test', '2026-11-27T10:00:00Z')
  await typeMessage('fix the flaky test')
  await press(messageBox(), 'Enter')
  turns[0].send('text', { text: 'On it.' })
  await settle()
  // The api names it from the message as the turn starts.
  expect(heading()).toBe('fix the flaky test')
  turns[0].send('done', { stopReason: 'end_turn', usage })
  await settle()
  // The reply is over: the box can send again while the title is still on its way.
  expect(byLabel('Send')).toBeTruthy()
  turns[0].send('title', { name: 'Flaky test fix' })
  turns[0].close()
  await settle()
  expect(heading()).toBe('Flaky test fix')
  expect(sidebarNames()).toContain('Flaky test fix')
  expect(document.title).toBe('Flaky test fix · Echo')
})

test('your own message is shown as Markdown', async () => {
  await open('/w/w9')
  await typeMessage('use **bold** here')
  await press(messageBox(), 'Enter')
  await settle()
  expect(document.querySelector('section[aria-label="Chat"] strong')?.textContent).toBe('bold')
})

test('a turn refused before it starts puts the message back and says why', async () => {
  refuseTurn = refused(409, 'agent_busy', 'This workspace has a turn in progress.')
  await open('/w/w9')
  await typeMessage('try again')
  await press(messageBox(), 'Enter')
  await settle()
  expect(document.body.textContent).toContain('This workspace has a turn in progress.')
  expect(messageBox().editor.getMarkdown()).toBe('try again')
  expect(document.querySelector('section[aria-label="Chat"] strong, section[aria-label="Chat"] p')?.textContent).not.toBe('try again')
})

test('a Learned link opens the panel, and the panel state is remembered', async () => {
  await open('/w/w9')
  expect(document.querySelector('section[aria-label="Workspace panel"]')).toBeNull()
  await typeMessage('learn something')
  await press(messageBox(), 'Enter')
  turns[0].send('done', { stopReason: 'end_turn', usage, learned: ['weekly-report'] })
  turns[0].close()
  await settle()
  await click(byText('button', 'weekly-report'))
  await settle()
  expect(document.querySelector('section[aria-label="Workspace panel"]')).toBeTruthy()
  expect(calls.some((c) => c.url.includes('path=.agent%2Fskills%2Fweekly-report%2FSKILL.md'))).toBe(true)
  expect(localStorage.getItem('echo.panel')).toBe('open')
  await click(byLabel('Close panel'))
  expect(localStorage.getItem('echo.panel')).toBe('closed')
  expect(byLabel('Files and preview').getAttribute('aria-pressed')).toBe('false')
})

test('leaving during a turn asks: Stay keeps it running, Leave stops it', async () => {
  await open('/w/w9')
  await typeMessage('long job')
  await press(messageBox(), 'Enter')
  turns[0].send('text', { text: 'Working on it' })
  await settle()

  await act(async () => router.navigate('/credentials'))
  await settle()
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain('The agent is still working')
  await click(byText('[role="dialog"] button', 'Stay'))
  await settle()
  expect(router.state.location.pathname).toBe('/w/w9')
  expect(turns[0].aborted).toBe(false)

  await act(async () => router.navigate('/'))
  await settle()
  await click(byText('[role="dialog"] button', 'Leave and stop'))
  await settle()
  expect(turns[0].aborted).toBe(true)
  expect(router.state.location.pathname).toBe('/')
})

test('Rename from the header menu keeps the field open and saves', async () => {
  await open('/w/w9')
  await click(byLabel('Workspace options'))
  await click(byText('[role="menuitem"]', 'Rename'))
  await settle()
  const input = byLabel('Workspace name') as HTMLInputElement
  expect(document.activeElement).toBe(input)
  workspace = ws('Renamed')
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'Renamed')
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await press(input, 'Enter')
  await settle()
  expect(calls.find((c) => c.method === 'PATCH')).toMatchObject({ url: '/api/agents/w9', body: { name: 'Renamed' } })
  expect(heading()).toBe('Renamed')
})

test('a missing workspace says so and links home', async () => {
  await open('/w/gone')
  expect(heading()).toBe('This workspace does not exist or was deleted')
  expect(byText('main a', 'Start a new workspace').getAttribute('href')).toBe('/')
})
