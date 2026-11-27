import { act, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { Composer } from '../composer/Composer'
import { AgentDialog } from '../pages/AgentDialog'
import { click, fakeLayout, messageBox, ok, press, refused, settle, typeMessage } from '../test/dom'
import { useMcpServers } from './workspaceCommands'

const server = (id: string, name: string, status = 'ok') => ({ id, name, kind: 'remote', url: `https://${name}.example.com/mcp`, status })
let all: unknown[]
let mine: string[]
let refuse: boolean
let puts: string[][]
let errors: string[]
let root: Root
let host: HTMLElement
let router: ReturnType<typeof createMemoryRouter>

function Page() {
  const mcp = useMcpServers('w1', (e) => errors.push(e))
  const [dialog, setDialog] = useState(false)
  return (
    <>
      <Composer draftKey="t" commands={[mcp.command]} onSend={async () => true} />
      <button onClick={() => setDialog(true)}>Name and purpose</button>
      {dialog && <AgentDialog title="Name and purpose" submitLabel="Save" initial={{ name: 'W', job: '', approval_mode: 'ask' }} mcp={mcp} onClose={() => setDialog(false)} onSubmit={async () => setDialog(false)} />}
    </>
  )
}

beforeEach(() => {
  all = [server('s1', 'linear'), server('s2', 'sentry', 'needs_auth'), server('s3', 'notes', 'tools_changed')]
  mine = ['s1']
  refuse = false
  puts = []
  errors = []
  fakeLayout()
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    if (url === '/api/mcp-servers') return ok(all)
    if (url === '/api/agents/w1/mcp-servers') {
      if (init.method === 'PUT') {
        const ids = JSON.parse(init.body as string).server_ids
        puts.push(ids)
        if (refuse) return refused(400, 'mcp_server_not_found', 'There is no MCP server with this id.')
        mine = ids
      }
      return ok((all as { id: string }[]).filter((s) => mine.includes(s.id)))
    }
    return refused(404, 'not_found', 'Not found.')
  })
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
  router = createMemoryRouter([{ path: '/', element: <Page /> }, { path: '/mcp', element: <p>connectors page</p> }], { initialEntries: ['/'] })
  await act(async () => root.render(<RouterProvider router={router} />))
  await settle()
}

const rows = () => Array.from(document.querySelectorAll('[role="option"]')) as HTMLElement[]
const button = (text: string) => Array.from(document.querySelectorAll('button')).find((b) => b.textContent === text)!
const statusText = () => Array.from(document.querySelectorAll('[role="status"]')).map((s) => s.textContent).join('|')

test('/mcp ticks the servers in use, says which need attention, and toggles several in a row', async () => {
  await open()
  await typeMessage('/mcp ')
  expect(rows().map((r) => r.textContent)).toEqual([
    'linearhttps://linear.example.com/mcpIn use',
    'sentryNeeds connecting in Connectors',
    'notesTools changed: review them in Connectors',
    'Open ConnectorsAdd, connect or review servers',
  ])
  await click(rows()[0])
  await settle()
  expect(statusText()).toContain('linear off for this workspace')
  // The menu stays open for the next pick.
  await click(rows()[2])
  await settle()
  expect(puts).toEqual([[], ['s3']])
  expect(rows()[2].textContent).toContain('In use')
  expect(rows()[0].textContent).not.toContain('In use')
})

test('a refused save keeps the old set and says why', async () => {
  refuse = true
  await open()
  await typeMessage('/mcp ')
  await click(rows()[1])
  await settle()
  expect(errors).toEqual(['MCP servers were not changed. There is no MCP server with this id.'])
  expect(rows()[0].textContent).toContain('In use')
  expect(rows()[1].textContent).not.toContain('In use')
})

test('with no servers the menu offers to add one', async () => {
  all = []
  mine = []
  await open()
  await typeMessage('/mcp ')
  expect(rows().map((r) => r.textContent)).toEqual(['Add an MCP serverYou have none yet'])
  await press(messageBox(), 'Enter')
  expect(router.state.location.pathname).toBe('/mcp')
})

test('the Name and purpose dialog shows the same set and saves a change', async () => {
  await open()
  await click(button('Name and purpose'))
  const box = (name: string) => Array.from(document.querySelectorAll('label')).find((l) => l.textContent?.startsWith(name))!.querySelector('input') as HTMLInputElement
  expect(box('linear').checked).toBe(true)
  expect(box('sentry').checked).toBe(false)
  // Saving without touching the list leaves it alone.
  await click(button('Save'))
  expect(puts).toEqual([])
  await click(button('Name and purpose'))
  await click(box('sentry'))
  await click(button('Save'))
  await settle()
  expect(puts).toEqual([['s1', 's2']])
  await typeMessage('/mcp ')
  expect(rows()[1].textContent).toContain('In use')
})
