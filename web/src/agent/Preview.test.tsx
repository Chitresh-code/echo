import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { Preview } from './Preview'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const ok = (data: unknown) => new Response(JSON.stringify({ success: true, data }), { status: 200 })
const refused = (status: number, code: string) => new Response(JSON.stringify({ success: false, error: { code, message: 'No.' } }), { status })

let calls: { method: string; url: string }[]
let previewAnswer: () => Response
let root: Root
let host: HTMLElement

beforeEach(() => {
  calls = []
  previewAnswer = () => ok({ url: 'http://a-3000.preview.localhost:8000/.echo-preview/start?token=t' })
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    calls.push({ method, url })
    if (url.endsWith('/processes') && method === 'GET') {
      return ok({
        processes: [
          { name: 'web', command: 'npm run dev', cwd: null, status: 'running', exit_code: null, started_at: 1 },
          { name: 'build', command: 'npm run build', cwd: null, status: 'exited', exit_code: 1, started_at: 1 },
        ],
        ports: [3000],
      })
    }
    if (url.endsWith('/preview')) return previewAnswer()
    if (method === 'DELETE') return ok({})
    return refused(404, 'not_found')
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

async function render(active = true) {
  await act(async () => root.render(<Preview agentId="a" active={active} />))
}

const button = (text: string) => [...host.querySelectorAll('button')].find((b) => b.textContent === text)!

async function click(el: Element) {
  await act(async () => (el as HTMLElement).click())
}

test('shows processes, their state and the listening ports', async () => {
  await render()
  const text = host.textContent ?? ''
  expect(text).toContain('web')
  expect(text).toContain('npm run dev')
  expect(text).toContain('running')
  expect(text).toContain('exited 1')
  expect(button('3000')).toBeTruthy()
  // Only a running process can be stopped.
  expect([...host.querySelectorAll('button')].filter((b) => b.textContent === 'Stop')).toHaveLength(1)
})

test('stop asks the api and reloads the list', async () => {
  await render()
  calls = []
  await click(button('Stop'))
  expect(calls[0]).toEqual({ method: 'DELETE', url: '/api/agents/a/processes/web' })
  expect(calls[1]).toEqual({ method: 'GET', url: '/api/agents/a/processes' })
})

test('a port opens in a sandboxed frame', async () => {
  await render()
  await click(button('3000'))
  const frame = host.querySelector('iframe')!
  expect(frame.getAttribute('src')).toBe('http://a-3000.preview.localhost:8000/.echo-preview/start?token=t')
  expect(frame.getAttribute('sandbox')).toBe('allow-scripts allow-forms allow-same-origin allow-popups allow-downloads')
})

test('with previews off it says so and shows no frame', async () => {
  previewAnswer = () => refused(404, 'preview_off')
  await render()
  await click(button('3000'))
  expect(host.querySelector('iframe')).toBeNull()
  expect(host.textContent).toContain('Previews are not set up')
})

test('a hidden view does not poll', async () => {
  await render(false)
  expect(calls).toEqual([])
})
