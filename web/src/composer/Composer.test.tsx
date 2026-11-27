import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { fakeLayout, messageBox as box, press as pressOn, typeMessage as type } from '../test/dom'
import { Composer, MESSAGE_CHARS } from './Composer'
import { matches, type Command } from './commands'

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

// Commands: a fake `/model` with two models, a loading row and a Retry row, and `/effort`.
let applied: string[] = []
const fakeCommands: Command[] = [
  {
    name: 'model',
    description: 'Choose the model',
    options: (q) =>
      [
        { id: 'alpha-mini', label: 'alpha-mini', group: 'Work key' },
        { id: 'beta-large', label: 'beta-large', group: 'Work key', selected: true },
        { id: 'loading', label: 'Loading the models', group: 'Home key', disabled: true },
        { id: 'retry', label: 'Retry', group: 'Old key' },
      ].filter((o) => matches(o.label, q)),
    apply: (o) => (o.id === 'retry' ? null : (applied.push(o.id), `Model set to ${o.label}`)),
  },
  { name: 'effort', description: 'How hard the model thinks', options: (q) => [{ id: 'high', label: 'high' }].filter((o) => matches(o.label, q)), apply: (o) => (applied.push(o.id), `Effort set to ${o.label}`) },
]
const menu = () => document.querySelector('[role="listbox"]') as HTMLElement | null
const options = () => Array.from(document.querySelectorAll('[role="option"]')).map((o) => o.textContent)
const status = () => Array.from(host.querySelectorAll('[role="status"]')).map((s) => s.textContent).join('')

test('/ at the start of a line opens the command menu; mid-line it is text', async () => {
  applied = []
  await render({ commands: fakeCommands })
  await type('look in /etc')
  expect(menu()).toBeNull()
  await act(async () => {
    editor().commands.clearContent()
  })
  await type('/')
  expect(options()).toEqual(['/modelChoose the model', '/effortHow hard the model thinks'])
  expect(status()).toBe('2 commands')
  await type('ef')
  expect(options()).toEqual(['/effortHow hard the model thinks'])
  // No command starts with this, so the menu closes and the text sends as typed.
  await type('x')
  expect(menu()).toBeNull()
  await press('Enter')
  expect(sent).toEqual(['/efx'])
})

test('picking a command lists its options; picking one applies it and clears the text', async () => {
  applied = []
  await render({ commands: fakeCommands })
  await type('/')
  await press('ArrowDown')
  await press('ArrowUp')
  await press('Enter')
  expect(editor().getText()).toBe('/model ')
  expect(options()).toEqual(['alpha-mini', 'beta-largeIn use', 'Loading the models', 'Retry'])
  expect(menu()!.querySelector('[role="group"]')?.getAttribute('aria-labelledby')).toBeTruthy()
  await type('beta')
  expect(options()).toEqual(['beta-largeIn use'])
  await press('Enter')
  expect(applied).toEqual(['beta-large'])
  expect(editor().isEmpty).toBe(true)
  expect(menu()).toBeNull()
  expect(status()).toBe('Model set to beta-large')
  expect(sent).toEqual([])
})

test('the menu works with the pointer, and a disabled or Retry row keeps the text', async () => {
  applied = []
  await render({ commands: fakeCommands })
  await type('/model ')
  const rows = () => document.querySelectorAll('[role="option"]') as NodeListOf<HTMLElement>
  await act(async () => rows()[2].click())
  await act(async () => rows()[3].click())
  expect(applied).toEqual([])
  expect(editor().getText()).toBe('/model ')
  await act(async () => rows()[0].click())
  expect(applied).toEqual(['alpha-mini'])
  expect(editor().isEmpty).toBe(true)
})

test('a known command is never sent; Escape closes the menu and then it sends as text', async () => {
  await render({ commands: fakeCommands })
  await type('/model zzz')
  expect(document.body.textContent).toContain('Nothing matches "zzz". Press Escape to send it as text.')
  await press('Enter')
  await press('Enter', { metaKey: true })
  await act(async () => sendButton().click())
  expect(sent).toEqual([])
  await press('Escape')
  expect(menu()).toBeNull()
  expect(editor().getText()).toBe('/model zzz')
  await press('Enter')
  expect(sent).toEqual(['/model zzz'])
})

test('the box points at the active row while the menu is open', async () => {
  await render({ commands: fakeCommands })
  await type('/')
  const listId = menu()!.id
  expect(box().getAttribute('aria-controls')).toBe(listId)
  expect(box().getAttribute('aria-activedescendant')).toBe(`${listId}-0`)
  await press('ArrowDown')
  expect(box().getAttribute('aria-activedescendant')).toBe(`${listId}-1`)
  await press('ArrowDown')
  expect(box().getAttribute('aria-activedescendant')).toBe(`${listId}-0`)
  await press('Escape')
  expect(box().hasAttribute('aria-controls')).toBe(false)
  expect(box().hasAttribute('aria-activedescendant')).toBe(false)
})

test('Enter during input method composition does not pick a row', async () => {
  applied = []
  await render({ commands: fakeCommands })
  await type('/model alpha')
  await press('Enter', { isComposing: true })
  expect(applied).toEqual([])
  expect(editor().getText()).toContain('/model alpha')
})

test('without commands, / is ordinary text', async () => {
  await render()
  await type('/model')
  expect(menu()).toBeNull()
  await press('Enter')
  expect(sent).toEqual(['/model'])
})
