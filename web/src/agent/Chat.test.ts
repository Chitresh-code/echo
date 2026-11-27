import { describe, expect, it } from 'vitest'
import { apply } from './Chat'

const usage = { inputTokens: 1, outputTokens: 2, cacheReadInputTokens: 0, cacheWriteInputTokens: 0 }

describe('apply', () => {
  it('names the skill on its tool row', () => {
    let m = apply({ role: 'agent', parts: [] }, { event: 'tool', data: { id: 't1', name: 'skills' } })
    m = apply(m, { event: 'tool', data: { id: 't2', name: 'shell' } })
    m = apply(m, { event: 'skill', data: { id: 't1', name: 'weekly-report' } })
    expect(m.parts).toEqual([
      { kind: 'tool', id: 't1', name: 'skills', skill: 'weekly-report' },
      { kind: 'tool', id: 't2', name: 'shell' },
    ])
  })

  it('keeps what the turn learned', () => {
    const m = apply({ role: 'agent', parts: [] }, { event: 'done', data: { stopReason: 'end_turn', usage, learned: ['weekly-report'] } })
    expect(m.learned).toEqual(['weekly-report'])
    expect(apply({ role: 'agent', parts: [] }, { event: 'done', data: { stopReason: 'end_turn', usage } }).learned).toBeUndefined()
  })

  it('puts what a call acted on and whether it failed on its row', () => {
    let m = apply({ role: 'agent', parts: [] }, { event: 'tool', data: { id: 't1', name: 'shell' } })
    m = apply(m, { event: 'tool_detail', data: { id: 't1', detail: 'npm test' } })
    m = apply(m, { event: 'tool_result', data: { id: 't1', ok: false } })
    m = apply(m, { event: 'tool_result', data: { id: 'unknown', ok: true } })
    expect(m.parts).toEqual([{ kind: 'tool', id: 't1', name: 'shell', detail: 'npm test', ok: false }])
  })

  it('turns a subagent call into a block that collects its work', () => {
    let m = apply({ role: 'agent', parts: [] }, { event: 'tool', data: { id: 's1', name: 'subagent' } })
    m = apply(m, { event: 'tool_result', data: { id: 's1', ok: true } }) // the "dispatched" acknowledgement
    m = apply(m, { event: 'delegate', data: { id: 's1', task: 'Find TODOs' } })
    m = apply(m, { event: 'delegate', data: { id: 's2', task: 'No row yet' } })
    m = apply(m, { event: 'delegate_tool', data: { delegate: 's1', id: 'c1', name: 'shell', detail: 'grep TODO' } })
    m = apply(m, { event: 'delegate_tool_result', data: { delegate: 's1', id: 'c1', ok: true } })
    m = apply(m, { event: 'delegate_done', data: { id: 's1', ok: true } })
    expect(m.parts).toEqual([
      { kind: 'delegate', id: 's1', task: 'Find TODOs', ok: true, tools: [{ kind: 'tool', id: 'c1', name: 'shell', detail: 'grep TODO', ok: true }] },
      { kind: 'delegate', id: 's2', task: 'No row yet', tools: [] },
    ])
  })

  it('hides the rows the plan already shows', () => {
    let m = apply({ role: 'agent', parts: [] }, { event: 'tool', data: { id: 't1', name: 'todo_write' } })
    m = apply(m, { event: 'tool', data: { id: 't2', name: 'strands_manage_background_task' } })
    expect(m.parts).toEqual([])
  })

  it('keeps one plan per message, updated where it first appeared', () => {
    let m = apply({ role: 'agent', parts: [] }, { event: 'todos', data: { items: [{ text: 'Read', status: 'in_progress' }] } })
    m = apply(m, { event: 'text', data: { text: 'Reading.' } })
    m = apply(m, { event: 'todos', data: { items: [{ text: 'Read', status: 'completed' }] } })
    expect(m.parts).toEqual([
      { kind: 'plan', items: [{ text: 'Read', status: 'completed' }] },
      { kind: 'text', text: 'Reading.' },
    ])
  })
  it('leaves the message as it is for a title, which renames the workspace instead', () => {
    const m = { role: 'agent' as const, parts: [] }
    expect(apply(m, { event: 'title', data: { name: 'Flaky test fix' } })).toBe(m)
  })

  it('adds an approval card and marks it answered', () => {
    const request = { id: 'a1', tool: 'shell', server: null, hints: null, subagent: null, input: { command: 'ls' } }
    let m = apply({ role: 'agent', parts: [] }, { event: 'approval_needed', data: request })
    m = apply(m, { event: 'approval_done', data: { id: 'a1', decision: 'deny' } })
    m = apply(m, { event: 'approval_done', data: { id: 'other', decision: 'allow' } })
    expect(m.parts).toEqual([{ kind: 'approval', ...request, decision: 'deny' }])
  })
})

describe('mcp_unavailable', () => {
  it('becomes a line with the reason and, for the user, the detail', () => {
    let m = apply({ role: 'agent', parts: [] }, { event: 'mcp_unavailable', data: { server: 'notes', reason: 'it exited while starting', detail: 'no module named x' } })
    m = apply(m, { event: 'mcp_unavailable', data: { server: 'old', reason: 'it needs connecting in Connectors' } })
    expect(m.parts).toEqual([
      { kind: 'unavailable', server: 'notes', reason: 'it exited while starting', detail: 'no module named x' },
      { kind: 'unavailable', server: 'old', reason: 'it needs connecting in Connectors', detail: '' },
    ])
  })
})
