import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { fakeLayout, messageBox as box, press as pressOn, typeMessage as type } from '../test/dom'
import { Composer, MESSAGE_CHARS } from './Composer'

let root: Root
let host: HTMLElement
let sent: string[]
let accept: boolean

beforeEach(() => {
  sent = []
  accept = true
  sessionStorage.clear()
  fakeLayout()
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
})

async function render(props: Partial<Parameters<typeof Composer>[0]> = {}) {
  await act(async () =>
    root.render(
      <Composer
        draftKey="w1"
        onSend={async (markdown) => {
          sent.push(markdown)
          return accept
        }}
        {...props}
      />,
    ),
  )
}

const editor = () => box().editor
const sendButton = () => host.querySelector('[aria-label="Send"]') as HTMLButtonElement

/** A real paste event, as the browser sends it, with plain text and optional HTML. */
async function paste(text: string, html = '') {
  await act(async () => {
    const event = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', { value: { getData: (type: string) => (type === 'text/html' ? html : type === 'text/plain' ? text : '') } })
    box().dispatchEvent(event)
  })
}

const press = (key: string, init: KeyboardEventInit = {}) => pressOn(box(), key, init)

test('Markdown shortcuts format the text and it is sent as the same Markdown', async () => {
  await render()
  await type('**bold** and')
  expect(box().querySelector('strong')?.textContent).toBe('bold')
  await press('Enter', { shiftKey: true })
  await type('- one')
  expect(box().querySelector('ul li')?.textContent).toBe('one')
  await press('Enter', { shiftKey: true })
  await type('two')
  expect(box().querySelectorAll('ul li')).toHaveLength(2)
  await press('Enter')
  expect(sent).toEqual(['**bold** and\n\n- one\n- two'])
  expect(editor().isEmpty).toBe(true)
})

test('Enter sends; in a code block it adds a line and Mod+Enter sends', async () => {
  await render()
  await type('```')
  await type(' ')
  expect(editor().isActive('codeBlock')).toBe(true)
  await type('x = 1')
  await press('Enter')
  expect(sent).toEqual([])
  await type('y = 2')
  await press('Enter', { metaKey: true })
  expect(sent).toEqual(['```\nx = 1\ny = 2\n```'])
})

test('Enter during input method composition does not send', async () => {
  await render()
  await type('にほん')
  await press('Enter', { isComposing: true })
  expect(sent).toEqual([])
  await press('Enter')
  expect(sent).toEqual(['にほん'])
})

test('an empty box, a running turn or a disabled box does not send', async () => {
  await render()
  await press('Enter')
  expect(sendButton().disabled).toBe(true)
  await render({ busy: true })
  await type('wait')
  await press('Enter')
  expect(host.querySelector('[aria-label="Stop"]')).toBeTruthy()
  await render({ disabled: true })
  await press('Enter')
  expect(sent).toEqual([])
  expect(box().getAttribute('contenteditable')).toBe('false')
})

test('over the limit it says so and keeps the text', async () => {
  await render()
  await act(async () => {
    editor().commands.setContent('a'.repeat(MESSAGE_CHARS + 1))
  })
  await press('Enter')
  expect(sent).toEqual([])
  expect(host.textContent).toContain('Too long to send: 100,001 of 100,000 characters')
  expect(editor().getText()).toHaveLength(MESSAGE_CHARS + 1)
})

test('a refused send puts the message back', async () => {
  accept = false
  await render()
  await type('**keep** me')
  await press('Enter')
  expect(sent).toEqual(['**keep** me'])
  expect(editor().getMarkdown()).toBe('**keep** me')
})

test('the draft survives leaving the page, and is gone after sending', async () => {
  await render()
  await type('half a *thought*')
  act(() => root.unmount())
  expect(sessionStorage.getItem('echo.draft.w1')).toBe('half a *thought*')
  root = createRoot(host)
  await render()
  expect(editor().getMarkdown()).toBe('half a *thought*')
  await press('Enter')
  expect(sessionStorage.getItem('echo.draft.w1')).toBeNull()
  // Each workspace has its own draft.
  act(() => root.unmount())
  root = createRoot(host)
  await render({ draftKey: 'w2' })
  expect(editor().isEmpty).toBe(true)
})

test('pasted Markdown becomes formatting, pasted HTML keeps only the text and allowed marks', async () => {
  await render()
  await paste('- a\n- **b**')
  expect(box().querySelectorAll('ul li')).toHaveLength(2)
  expect(box().querySelector('strong')?.textContent).toBe('b')
  await act(async () => {
    editor().commands.clearContent()
  })
  await paste('Title Hi there', '<h1>Title</h1><p>Hi <img src=x onerror="alert(1)"><script>alert(2)</script><em>there</em></p>')
  expect(box().querySelector('img, script, h1')).toBeNull()
  expect(editor().getMarkdown()).toBe('Title\n\nHi *there*')
})

test('a file name stays text; a web address typed out becomes a link', async () => {
  await render()
  await type('fix hello.py ')
  await type('see https://example.com ')
  expect(box().querySelectorAll('a')).toHaveLength(1)
  expect(box().querySelector('a')?.getAttribute('href')).toBe('https://example.com')
  await press('Enter')
  expect(sent[0]).toContain('fix hello.py')
  expect(sent[0]).not.toContain('](http://hello.py)')
})
