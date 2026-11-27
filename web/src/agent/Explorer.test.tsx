import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { Explorer, type NewKind } from './Explorer'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const tree = { entries: [{ path: 'src', type: 'dir' as const }, { path: 'src/a.ts', type: 'file' as const }, { path: 'README.md', type: 'file' as const }], truncated: false }
let root: Root
let host: HTMLElement
let created: [NewKind, string][]
let sent: FormData[]
let answers: Response[]

const ok = (data: unknown) => new Response(JSON.stringify({ success: true, data }), { status: 200 })

beforeEach(async () => {
  created = []
  sent = []
  answers = []
  vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => {
    sent.push(init.body as FormData)
    return answers.shift()!
  })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  await act(async () =>
    root.render(
      <Explorer
        agentId="a"
        tree={tree}
        letters={new Map()}
        active={null}
        onOpen={() => {}}
        onRefresh={() => {}}
        onCreate={async (kind, path) => void created.push([kind, path])}
        storage={null}
      />,
    ),
  )
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
})

const button = (label: string) => host.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!
const input = () => host.querySelector<HTMLInputElement>('input[aria-label^="New"]')
const click = (el: HTMLElement) => act(async () => el.click())

async function type(value: string) {
  const el = input()!
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => {
    set.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

const enter = () => act(async () => input()!.form!.requestSubmit())

test('the name box opens inside the folder, says a name is taken, and creates on Enter', async () => {
  await click(button('New file in src'))
  // Under src, before its file.
  const items = [...host.querySelectorAll('li')]
  expect(items.findIndex((li) => li.contains(input()))).toBe(1)
  await type('a.ts')
  expect(host.textContent).toContain('a.ts already exists here')
  await enter()
  expect(created).toEqual([])
  await type('lib/b.ts')
  await enter()
  expect(created).toEqual([['file', 'src/lib/b.ts']])
  expect(input()).toBeNull()
})

test('Escape cancels and a blur with nothing typed makes nothing', async () => {
  await click(button('New folder'))
  await act(async () => input()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
  expect(input()).toBeNull()
  await click(button('New folder'))
  await act(async () => input()!.blur())
  expect(input()).toBeNull()
  expect(created).toEqual([])
})

test('a taken upload asks, and Replace sends it again with overwrite', async () => {
  answers = [
    new Response(JSON.stringify({ success: false, error: { code: 'files_exist', message: 'Taken.', details: { paths: ['README.md'] } } }), { status: 409 }),
    ok({ written: ['README.md'] }),
  ]
  const picker = host.querySelector<HTMLInputElement>('input[type=file]')!
  Object.defineProperty(picker, 'files', { value: [new File(['hi'], 'README.md')], configurable: true })
  await act(async () => picker.dispatchEvent(new Event('change', { bubbles: true })))
  expect(document.body.textContent).toContain('Replace README.md?')
  const replace = [...document.querySelectorAll('button')].find((b) => b.textContent === 'Replace')!
  await click(replace)
  expect(sent.map((f) => f.get('overwrite'))).toEqual(['false', 'true'])
  expect(host.textContent).toContain('Uploaded 1 file.')
})

test('a file over 5 MB is refused before sending', async () => {
  const picker = host.querySelector<HTMLInputElement>('input[type=file]')!
  const big = new File(['x'], 'big.bin')
  Object.defineProperty(big, 'size', { value: 6 * 1024 * 1024 })
  Object.defineProperty(picker, 'files', { value: [big], configurable: true })
  await act(async () => picker.dispatchEvent(new Event('change', { bubbles: true })))
  expect(host.textContent).toContain('big.bin is larger than 5 MB')
  expect(sent).toEqual([])
})
