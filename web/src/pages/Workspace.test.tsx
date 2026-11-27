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
const ws = (name: string, used: string | null = null) => ({ id: 'w9', name, job: '', created_at: '2026-11-27T00:00:00Z', last_used_at: used, approval_mode: 'ask' })
const usage = { inputTokens: 10, outputTokens: 5, cacheReadInputTokens: 0, cacheWriteInputTokens: 0 }

/** A turn's event stream that the test writes to, and that ends when the page aborts the request.
 *  Like the server's, it starts with the turn's id. */
function turnStream(signal?: AbortSignal | null) {
  let ctl!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({ start: (c) => void (ctl = c) })
  const turn = {
    url: '',
    aborted: false,
    response: new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }),
    send: (event: string, data: unknown) => ctl.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)),
    close: () => ctl.close(),
    drop: () => ctl.error(new TypeError('network error')),
  }
  turn.send('turn', { id: 't1' })
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
let stored: Record<string, unknown> | null
let listed: { id: string; title: string; created_at: string; updated_at: string; running: boolean }[]
let listFails: boolean
let patchFails: boolean
let answerGone: boolean
let root: Root
let host: HTMLElement
let router: ReturnType<typeof createMemoryRouter>

beforeEach(() => {
  calls = []
  turns = []
  refuseTurn = null
  stored = null
  listed = []
  listFails = false
  patchFails = false
  answerGone = false
  workspace = ws('New workspace')
  fakeLayout()
  Element.prototype.scrollIntoView = () => {}
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    calls.push({ method, url, body: init.body ? JSON.parse(init.body as string) : undefined })
    if (url === '/api/auth/me') return ok({ id: 'u', name: 'Ada Lovelace', email: 'ada@example.com' })
    if (url === '/api/agents') return method === 'POST' ? ok(workspace) : ok([workspace])
    if (url === '/api/agents/w9' && method === 'PATCH') {
      if (patchFails) return refused(503, 'unavailable', 'The service is busy. Try again in a moment.')
      workspace = { ...workspace, ...JSON.parse(init.body as string) }
      return ok(workspace)
    }
    if (url.startsWith('/api/agents/w9/approvals/')) {
      return answerGone ? refused(404, 'approval_not_found', 'Nothing is waiting.') : ok(JSON.parse(init.body as string))
    }
    if (url === '/api/agents/w9') return ok(workspace)
    if (url === '/api/agents/gone') return refused(404, 'not_found', 'This workspace does not exist.')
    if (url === '/api/credentials') return ok([KEY])
    if (url.endsWith('/tree')) return ok({ entries: [], truncated: false })
    if (url.endsWith('/git/status')) return ok([])
    if (url.endsWith('/chats') && method === 'POST') return ok({ id: 'c1' })
    if (/^\/api\/agents\/w9\/chats\/c1[0]*$/.test(url)) return stored ? ok(stored) : refused(404, 'chat_not_found', 'This chat does not exist.')
    if (url.endsWith('/stop')) return ok({ stopping: true })
    if (url.startsWith('/api/agents/w9/chats?') || (url === '/api/agents/w9/chats' && method === 'GET')) {
      if (listFails) return refused(503, 'unavailable', 'The service is busy. Try again in a moment.')
      const page = url.includes('before=') ? listed.slice(1) : listed.slice(0, 1)
      return ok({ chats: page, more: !url.includes('before=') && listed.length > 1 })
    }
    if (method === 'DELETE' && url.startsWith('/api/agents/w9/chats/')) return ok({ deleted: true })
    if (url.endsWith('/turns') || url.endsWith('/events')) {
      if (refuseTurn && method === 'POST') return refuseTurn
      const turn = turnStream(init.signal)
      turn.url = url
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
  expect(router.state.location.pathname).toBe('/w/w9/c/c1')
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

const chatText = () => document.querySelector('section[aria-label="Chat"]')?.textContent ?? ''
const storedChat = (status: string, events: unknown[]) => ({
  id: 'c1', title: 'long job', created_at: '2026-11-27T10:00:00Z', updated_at: '2026-11-27T10:00:00Z', running: status === 'running', more: false,
  turns: [{ id: 't1', prompt: 'long job', model: null, effort: null, status, usage: null, truncated: false, started_at: '2026-11-27T10:00:00Z', ended_at: status === 'running' ? null : '2026-11-27T10:00:09Z', events }],
})

test('a new chat gets its own address without losing the turn on screen', async () => {
  await open('/w/w9')
  await typeMessage('long job')
  await press(messageBox(), 'Enter')
  turns[0].send('text', { text: 'Working on it' })
  await settle()
  expect(router.state.location.pathname).toBe('/w/w9/c/c1')
  expect(chatText()).toContain('Working on it')
  expect(turns[0].aborted).toBe(false)
})

test('leaving does not stop the turn, and coming back follows it', async () => {
  await open('/w/w9')
  await typeMessage('long job')
  await press(messageBox(), 'Enter')
  turns[0].send('text', { text: 'Working on it' })
  await settle()
  await act(async () => router.navigate('/credentials'))
  await settle()
  // Only this page stopped reading; nothing asked, and nothing was sent to stop it.
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  expect(calls.some((c) => c.url.endsWith('/stop'))).toBe(false)

  stored = storedChat('running', [{ event: 'text', data: { text: 'Working on it' } }])
  await act(async () => router.navigate('/w/w9/c/c1'))
  await settle()
  expect(turns[1].url).toBe('/api/agents/w9/chats/c1/turns/t1/events')
  // The replay rebuilds the message, so what was stored is not shown twice.
  turns[1].send('text', { text: 'Working on it, nearly done' })
  await settle()
  expect(chatText()).toContain('Working on it, nearly done')
  expect(chatText()).not.toContain('Working on itWorking on it')
  turns[1].send('done', { stopReason: 'end_turn', usage })
  await settle()
  expect(byLabel('Send')).toBeTruthy()
})

test('a dropped stream reconnects and picks the turn up again', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  try {
    await open('/w/w9')
    await typeMessage('long job')
    await press(messageBox(), 'Enter')
    turns[0].send('text', { text: 'Step one' })
    await settle()
    turns[0].drop()
    await settle()
    expect(chatText()).toContain('Reconnecting')
    await act(async () => vi.advanceTimersByTime(1000))
    await settle()
    expect(turns[1].url).toBe('/api/agents/w9/chats/c1/turns/t1/events')
    turns[1].send('text', { text: 'Step one, step two' })
    await settle()
    expect(chatText()).toContain('Step one, step two')
    expect(chatText()).not.toContain('Reconnecting')
  } finally {
    vi.useRealTimers()
  }
})

test('Stop asks the server, and the turn ends when it says stopped', async () => {
  await open('/w/w9')
  await typeMessage('long job')
  await press(messageBox(), 'Enter')
  await settle()
  await click(byLabel('Stop'))
  await settle()
  expect(calls.some((c) => c.method === 'POST' && c.url === '/api/agents/w9/chats/c1/turns/t1/stop')).toBe(true)
  turns[0].send('stopped', {})
  await settle()
  expect(byLabel('Send')).toBeTruthy()
})

test('a stored chat shows its turns, and one cut off by a restart says so', async () => {
  stored = storedChat('interrupted', [{ event: 'text', data: { text: 'Halfway' } }])
  await open('/w/w9/c/c1')
  expect(chatText()).toContain('long job')
  expect(chatText()).toContain('Halfway')
  expect(chatText()).toContain('The server restarted during this turn')
  expect(turns).toHaveLength(0)
})

test('a deleted chat says so and opens a new one', async () => {
  await open('/w/w9/c/c1')
  expect(router.state.location.pathname).toBe('/w/w9')
  expect(document.body.textContent).toContain('This chat does not exist')
})

test('a tab from before chats had addresses goes back to its chat', async () => {
  const old = 'c1'.padEnd(32, '0')
  stored = { ...storedChat('done', []), id: old }
  sessionStorage.setItem('echo.chat.w9', old)
  await open('/w/w9')
  expect(router.state.location.pathname).toBe(`/w/w9/c/${old}`)
  expect(sessionStorage.getItem('echo.chat.w9')).toBeNull()
})

const summary = (id: string, title: string, running = false) => ({ id, title, created_at: '2026-11-27T10:00:00Z', updated_at: '2026-11-27T10:00:00Z', running })
const listLinks = () => [...document.querySelectorAll('[role="dialog"][aria-label="Chats"] li a')].map((a) => a.textContent)

test('the chat list opens a chat, pages, and marks one still running', async () => {
  listed = [summary('c1', 'long job', true), summary('c2'.padEnd(32, '0'), 'older chat')]
  stored = storedChat('done', [{ event: 'text', data: { text: 'All done' } }])
  await open('/w/w9')
  await click(byLabel('Chats'))
  await settle()
  expect(listLinks()).toEqual(['long jobWorking now'])
  await click(byText('[role="dialog"] button', 'Show more'))
  await settle()
  expect(listLinks()).toHaveLength(2)
  expect((byLabel('Delete chat long job') as HTMLButtonElement).disabled).toBe(true)
  await click(document.querySelector('[role="dialog"][aria-label="Chats"] li a') as HTMLElement)
  await settle()
  expect(router.state.location.pathname).toBe('/w/w9/c/c1')
  expect(chatText()).toContain('All done')
})

test('the chat list says when it is empty, and offers Retry when it fails', async () => {
  listFails = true
  await open('/w/w9')
  await click(byLabel('Chats'))
  await settle()
  expect(document.body.textContent).toContain('The chats could not be loaded. The service is busy.')
  listFails = false
  await click(byText('[role="dialog"] button', 'Retry'))
  await settle()
  expect(document.body.textContent).toContain('No chats yet.')
})

test('deleting the open chat asks first, then starts a new one', async () => {
  listed = [summary('c1', 'long job')]
  stored = storedChat('done', [])
  await open('/w/w9/c/c1')
  await click(byLabel('Chats'))
  await settle()
  await click(byLabel('Delete chat long job'))
  await settle()
  expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  await click(byText('[role="dialog"] button', 'Delete'))
  await settle()
  expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/agents/w9/chats/c1')).toBe(true)
  expect(router.state.location.pathname).toBe('/w/w9')
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

const CARD = { id: 'a1', tool: 'shell', server: null, hints: null, subagent: 'Survey the tests', input: { command: 'rm -rf build' } }
const card = () => document.querySelector('[role="group"][aria-label="Approval for shell"]') as HTMLElement
const button = (text: string) => byText('button', text) as HTMLButtonElement
const settingsLabel = () => document.querySelector('[aria-label^="Model "]') as HTMLElement

async function startTurn() {
  await open('/w/w9')
  await typeMessage('clean up')
  await press(messageBox(), 'Enter')
  await settle()
}

test('an approval card shows the call, posts the answer once, and shows how it was answered', async () => {
  await startTurn()
  turns[0].send('approval_needed', CARD)
  await settle()
  expect(card().textContent).toContain('shell')
  expect(card().textContent).toContain('Survey the tests')
  expect(card().textContent).toContain('"command": "rm -rf build"')
  expect(document.body.textContent).toContain('Waiting for your approval…')
  await click(button('Allow for this chat'))
  await settle()
  expect(calls.filter((c) => c.url.includes('/approvals/'))).toEqual([{ method: 'POST', url: '/api/agents/w9/approvals/a1', body: { decision: 'always' } }])
  expect(button('Allow').disabled).toBe(true)
  turns[0].send('approval_done', { id: 'a1', decision: 'always' })
  await settle()
  expect(card().textContent).toContain('Allowed for the rest of this chat')
  expect(button('Allow')).toBeUndefined()
  expect(document.body.textContent).toContain('Working…')
})

test('an answer that comes too late says so and the card stays answerable from the stream', async () => {
  answerGone = true
  await startTurn()
  turns[0].send('approval_needed', { ...CARD, subagent: null })
  await settle()
  await click(button('Deny'))
  await settle()
  expect(card().textContent).toContain('already answered or has timed out')
  expect(button('Deny').disabled).toBe(false)
  turns[0].send('approval_done', { id: 'a1', decision: 'timeout' })
  turns[0].send('done', { stopReason: 'end_turn', usage })
  await settle()
  expect(card().textContent).toContain('No one answered in 10 minutes')
})

test('a stored turn that ended with a card unanswered says the call did not run', async () => {
  stored = {
    id: 'c1', title: 'x', created_at: '2026-11-27T00:00:00Z', updated_at: '2026-11-27T00:00:00Z', more: false,
    turns: [{ id: 't1', prompt: 'go', status: 'stopped', started_at: '2026-11-27T00:00:00Z', ended_at: '2026-11-27T00:00:05Z', truncated: false,
      events: [['approval_needed', CARD], ['stopped', {}]].map(([event, data]) => ({ event, data })) }],
  }
  await open('/w/w9/c/c1')
  expect(card().textContent).toContain('The turn ended before this was answered')
  expect(button('Allow')).toBeUndefined()
})

test('/approvals switches to yolo, the label says so, and a refused save keeps ask', async () => {
  await open('/w/w9')
  await typeMessage('/approvals ')
  await settle()
  const rows = () => [...document.querySelectorAll('[role="option"]')].map((r) => r.textContent)
  expect(rows()).toEqual(['Ask before toolsYou approve commands, file changes and web requests firstIn use', 'YoloEvery call runs without asking'])
  await press(messageBox(), 'ArrowDown')
  await press(messageBox(), 'Enter')
  await settle()
  expect(calls.find((c) => c.method === 'PATCH')).toMatchObject({ url: '/api/agents/w9', body: { approval_mode: 'yolo' } })
  expect(settingsLabel().textContent).toBe('claude-haiku-5-5 · yolo')

  patchFails = true
  await typeMessage('/approvals ask')
  await settle()
  await press(messageBox(), 'Enter')
  await settle()
  expect(document.body.textContent).toContain('Approvals were not changed. The service is busy.')
  expect(settingsLabel().textContent).toBe('claude-haiku-5-5 · yolo')
})

test('Name and purpose saves the approval mode', async () => {
  await open('/w/w9')
  await click(byLabel('Workspace options'))
  await click(byText('[role="menuitem"]', 'Name and purpose…'))
  await settle()
  const ask = document.querySelector('input[type="checkbox"]') as HTMLInputElement
  expect(ask.checked).toBe(true)
  await click(ask)
  await click(button('Save'))
  await settle()
  expect(calls.find((c) => c.method === 'PATCH')).toMatchObject({ body: { name: 'New workspace', job: '', approval_mode: 'yolo' } })
  expect(settingsLabel().textContent).toBe('claude-haiku-5-5 · yolo')
})
