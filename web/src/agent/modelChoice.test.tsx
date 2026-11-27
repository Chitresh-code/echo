import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { Composer } from '../composer/Composer'
import { SettingsLabel } from '../composer/SettingsLabel'
import { click, fakeLayout, messageBox, ok, press, refused, settle, typeMessage } from '../test/dom'
import { useModelChoice } from './modelChoice'

const KEYS = [
  { id: 'k1', label: 'Work', provider: 'openai', created_at: '2026-11-01T00:00:00Z' },
  { id: 'k2', label: 'Local', provider: 'openai_compatible', base_url: 'https://llm.example.com/v1', created_at: '2026-11-01T00:00:00Z' },
  { id: 'k3', label: 'Old', provider: 'anthropic', created_at: '2026-11-01T00:00:00Z' },
]
let keys: unknown[]
let k3Fails: boolean
let calls: string[]
let sent: { markdown: string; effort: string; model?: string }[]
let root: Root
let host: HTMLElement
let router: ReturnType<typeof createMemoryRouter>

function Page() {
  const models = useModelChoice()
  return (
    <Composer
      draftKey="t"
      commands={models.commands}
      footer={<SettingsLabel state={models} />}
      onSend={async (markdown) => (sent.push({ markdown, effort: models.effort, model: models.choice?.model }), true)}
    />
  )
}

beforeEach(() => {
  keys = KEYS
  k3Fails = true
  calls = []
  sent = []
  fakeLayout()
  vi.stubGlobal('fetch', async (url: string) => {
    calls.push(url)
    if (url === '/api/credentials') return ok(keys)
    if (url === '/api/credentials/k1/models') return ok([{ id: 'gpt-5.4-mini', name: '' }, { id: 'gpt-5.4', name: '' }])
    if (url === '/api/credentials/k2/models') return ok([{ id: 'llama-4', name: '' }])
    if (url === '/api/credentials/k3/models') return k3Fails ? refused(502, 'provider_error', 'Anthropic did not answer.') : ok([{ id: 'claude-haiku-5-5', name: '' }])
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

async function open() {
  router = createMemoryRouter([{ path: '/', element: <Page /> }, { path: '/credentials', element: <p>credentials page</p> }], { initialEntries: ['/'] })
  await act(async () => root.render(<RouterProvider router={router} />))
  await settle()
}

const rows = () => Array.from(document.querySelectorAll('[role="option"]')) as HTMLElement[]
const labels = () => rows().map((r) => r.textContent)
const label = () => document.querySelector('[aria-label^="Model "]') as HTMLElement
const statusText = () => Array.from(document.querySelectorAll('[role="status"]')).map((s) => s.textContent).join('|')

test('/model lists every key\'s models in groups and loads them only when asked', async () => {
  await open()
  expect(calls).toEqual(['/api/credentials'])
  expect(label().textContent).toBe('Choose a model')
  await typeMessage('/model ')
  await settle()
  const groups = Array.from(document.querySelectorAll('[role="group"]')).map((g) => document.getElementById(g.getAttribute('aria-labelledby')!)?.textContent)
  expect(groups).toEqual(['Work · OpenAI', 'Local · OpenAI-compatible', 'Old · Anthropic'])
  expect(labels()).toEqual(['gpt-5.4-mini', 'gpt-5.4', 'llama-4', 'RetryAnthropic did not answer.'])
  await typeMessage('mini')
  await press(messageBox(), 'Enter')
  expect(label().textContent).toBe('gpt-5.4-mini')
  expect(statusText()).toContain('Model set to gpt-5.4-mini')
  // The menu marks the model in use.
  await typeMessage('/model ')
  expect(rows()[0].textContent).toBe('gpt-5.4-miniIn use')
})

test('Retry on a key whose models failed reloads only that key', async () => {
  await open()
  await typeMessage('/model ')
  await settle()
  k3Fails = false
  await click(rows().find((r) => r.textContent?.startsWith('Retry'))!)
  await settle()
  expect(labels()).toContain('claude-haiku-5-5')
  expect(calls.filter((c) => c.endsWith('/models'))).toEqual(['/api/credentials/k1/models', '/api/credentials/k2/models', '/api/credentials/k3/models', '/api/credentials/k3/models'])
  expect(messageBox().editor.getText()).toBe('/model ')
})

test('an OpenAI-compatible key takes only auto effort, and a stored effort is sent as auto', async () => {
  localStorage.setItem('echo.effort', JSON.stringify('high'))
  localStorage.setItem('echo.model', JSON.stringify({ credentialId: 'k1', model: 'gpt-5.4' }))
  await open()
  expect(label().textContent).toBe('gpt-5.4 · high')
  await typeMessage('/model llama')
  await settle()
  await press(messageBox(), 'Enter')
  expect(statusText()).toContain("Effort set to auto, the only level this key's service takes.")
  expect(label().textContent).toBe('llama-4')
  await typeMessage('/effort ')
  expect(labels()).toEqual(["autoThe only level this key's service takesIn use"])
  await press(messageBox(), 'Escape')
  await act(async () => messageBox().editor.commands.clearContent())
  // Someone who stored high before, on a compatible key, sends auto.
  localStorage.setItem('echo.effort', JSON.stringify('high'))
  localStorage.setItem('echo.model', JSON.stringify({ credentialId: 'k2', model: 'llama-4' }))
  act(() => root.unmount())
  root = createRoot(host)
  await open()
  expect(label().textContent).toBe('llama-4')
  await typeMessage('go')
  await press(messageBox(), 'Enter')
  expect(sent).toEqual([{ markdown: 'go', effort: 'auto', model: 'llama-4' }])
})

test('/effort sets the effort, which is remembered', async () => {
  localStorage.setItem('echo.model', JSON.stringify({ credentialId: 'k1', model: 'gpt-5.4' }))
  await open()
  await typeMessage('/effort ')
  expect(labels().map((l) => l?.replace('In use', ''))).toEqual(["auto The model's own default".replace(' ', ''), 'offNo extra thinking', 'low', 'medium', 'high'])
  await typeMessage('hi')
  await press(messageBox(), 'Enter')
  expect(label().textContent).toBe('gpt-5.4 · high')
  expect(JSON.parse(localStorage.getItem('echo.effort')!)).toBe('high')
})

test('the label opens a searchable list of every setting', async () => {
  localStorage.setItem('echo.model', JSON.stringify({ credentialId: 'k1', model: 'gpt-5.4' }))
  await open()
  expect(label().getAttribute('aria-label')).toBe('Model gpt-5.4, effort auto. Change')
  await click(label())
  await settle()
  const search = document.querySelector('input[aria-label="Search models and effort"]') as HTMLInputElement
  expect(document.activeElement).toBe(search)
  expect(labels()).toContain('gpt-5.4-mini')
  expect(labels()).toContain('medium')
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    set.call(search, 'medi')
    search.dispatchEvent(new Event('input', { bubbles: true }))
  })
  expect(labels()).toEqual(['medium'])
  await press(search, 'Enter')
  await settle()
  expect(document.querySelector('input[aria-label="Search models and effort"]')).toBeNull()
  expect(label().textContent).toBe('gpt-5.4 · medium')
  expect(statusText()).toContain('Effort set to medium')
})

test('with no keys, /model offers to add one', async () => {
  keys = []
  await open()
  expect(host.textContent).toContain('Add a model key to start a chat.')
  await typeMessage('/model ')
  expect(labels()).toEqual(['Add a model keyOpens Credentials'])
  await press(messageBox(), 'Enter')
  expect(router.state.location.pathname).toBe('/credentials')
})
