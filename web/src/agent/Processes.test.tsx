import { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ok, refused } from '../test/dom'
import { useOpenFiles, previewKey } from './files'
import { usePorts } from './ports'
import { PreviewFrame } from './PreviewFrame'
import { Processes } from './Processes'

let calls: { method: string; url: string }[]
let ports: number[]
let previewAnswer: () => Response
let root: Root
let host: HTMLElement

beforeEach(() => {
  calls = []
  ports = [3000]
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
        ports,
      })
    }
    if (url.endsWith('/logs')) return ok({ name: 'web', log: 'ready on 3000' })
    if (url.endsWith('/preview')) return previewAnswer()
    if (method === 'DELETE') return ok({})
    if (url.includes('/file?')) return ok({ path: 'a.txt', content: 'x', encoding: 'utf-8' })
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
const button = (text: string) => [...host.querySelectorAll('button')].find((b) => b.textContent === text)!
const click = async (el: Element) => { await act(async () => (el as HTMLElement).click()); await flush() }

// The panel's wiring, without Monaco: the hooks, the Processes list and a line of state.
let api: { files: ReturnType<typeof useOpenFiles>; ports: ReturnType<typeof usePorts> }
function Harness({ open = true }: { open?: boolean }) {
  const files = useOpenFiles('a')
  const p = usePorts('a', open, files)
  const [shown, setShown] = useState<number | null>(null)
  api = { files, ports: p }
  return (
    <>
      <output data-tabs={files.previews.join(',')} data-active={files.active ?? ''} data-shown={shown ?? ''} />
      <Processes agentId="a" ports={p} onShow={(port) => (setShown(port), files.openPreview(port))} />
    </>
  )
}
const state = () => {
  const o = host.querySelector('output')!
  return { tabs: o.dataset.tabs, active: o.dataset.active }
}

test('shows processes, their state, output and the listening ports', async () => {
  await act(async () => root.render(<Harness />))
  await flush()
  const text = host.textContent ?? ''
  expect(text).toContain('npm run dev')
  expect(text).toContain('exited 1')
  expect(button('3000')).toBeTruthy()
  expect([...host.querySelectorAll('button')].filter((b) => b.textContent === 'Stop')).toHaveLength(1)
  await click(button('Output'))
  expect(host.textContent).toContain('ready on 3000')
  calls = []
  await click(button('Stop'))
  expect(calls[0]).toEqual({ method: 'DELETE', url: '/api/agents/a/processes/web' })
  expect(calls[1]).toEqual({ method: 'GET', url: '/api/agents/a/processes' })
})

test('a listening port opens its tab, and in the background when a file is open', async () => {
  ports = []
  await act(async () => root.render(<Harness />))
  await flush()
  await act(async () => { await api.files.open('a.txt', false) })
  ports = [3000]
  await act(async () => { await api.ports.load() })
  expect(state()).toEqual({ tabs: '3000', active: 'a.txt' })
  // With nothing open, the new tab is shown.
  act(() => api.files.close('a.txt'))
  act(() => api.ports.dismiss(3000))
  ports = [3000, 5173]
  await act(async () => { await api.ports.load() })
  expect(state()).toEqual({ tabs: '5173', active: previewKey(5173) })
})

test('a closed preview stays closed until its port stops and listens again', async () => {
  await act(async () => root.render(<Harness />))
  await flush()
  expect(state().tabs).toBe('3000')
  act(() => api.ports.dismiss(3000))
  await act(async () => { await api.ports.load() })
  expect(state().tabs).toBe('')
  ports = []
  await act(async () => { await api.ports.load() })
  ports = [3000]
  await act(async () => { await api.ports.load() })
  expect(state().tabs).toBe('3000')
  // The Listening button opens it on demand too.
  act(() => api.ports.dismiss(3000))
  await click(button('3000'))
  expect(state()).toEqual({ tabs: '3000', active: previewKey(3000) })
})

test('a closed panel does not poll', async () => {
  await act(async () => root.render(<Harness open={false} />))
  await flush()
  expect(calls).toEqual([])
})

test('a preview is a sandboxed frame with a full screen button', async () => {
  await act(async () => root.render(<PreviewFrame agentId="a" port={3000} listening shown />))
  await flush()
  const frame = host.querySelector('iframe')!
  expect(frame.getAttribute('src')).toBe('http://a-3000.preview.localhost:8000/.echo-preview/start?token=t')
  expect(frame.getAttribute('sandbox')).toBe('allow-scripts allow-forms allow-same-origin allow-popups allow-downloads')
  const requestFullscreen = vi.fn(() => Promise.resolve())
  host.querySelector('section')!.requestFullscreen = requestFullscreen
  await click(host.querySelector('[aria-label="Full screen"]')!)
  expect(requestFullscreen).toHaveBeenCalled()
})

test('with previews off the tab says so and shows no frame', async () => {
  previewAnswer = () => refused(404, 'preview_off', 'Off.')
  await act(async () => root.render(<PreviewFrame agentId="a" port={3000} listening={false} shown />))
  await flush()
  expect(host.querySelector('iframe')).toBeNull()
  expect(host.textContent).toContain('Previews are not set up')
  expect(host.textContent).toContain('Nothing is listening on port 3000')
})
