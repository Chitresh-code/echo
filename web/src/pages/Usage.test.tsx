import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { UsageReport } from '../api/types'
import { money } from '../format'
import { click, fakeLayout, ok, refused, settle } from '../test/dom'
import { range, Usage } from './Usage'

// The chart measures its container, which jsdom cannot; the page around it is what is tested here.
vi.mock('@mui/x-charts/BarChart', () => ({ BarChart: () => <div data-testid="chart" /> }))

const share = (id: string, name: string | null, cost: number, extra = {}) => ({ id, name, provider: null, cost_micros: cost, tokens: 1200, turns: 2, unpriced_tokens: 0, ...extra })
const REPORT: UsageReport = {
  totals: { cost_micros: 1_234_567, input_tokens: 10_000, output_tokens: 2_000, cache_read_tokens: 0, cache_write_tokens: 0, turns: 3, unpriced_tokens: 500 },
  days: [{ date: '2026-11-26', cost_micros: 0, tokens: 0 }, { date: '2026-11-27', cost_micros: 1_234_567, tokens: 12_000 }],
  workspaces: [share('w1', 'Billing service', 1_000_000), share('w2', null, 234_567)],
  models: [share('anthropic/claude-opus-5-5', 'claude-opus-5-5', 1_234_567), share('openai_compatible/llama', 'llama', 0, { unpriced_tokens: 500 })],
  keys: [share('k1', null, 1_234_567)],
  prices: { source: 'https://example.com/prices.json', fetched: '2026-11-27' },
  since: '2026-11-20T10:00:00Z',
}

let answer: () => Response
let urls: string[]
let root: Root
let host: HTMLElement

beforeEach(() => {
  urls = []
  answer = () => ok(REPORT)
  fakeLayout()
  vi.stubGlobal('fetch', async (url: string) => {
    urls.push(url)
    return answer()
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

async function show() {
  await act(async () => root.render(<Usage />))
  await settle()
}

test('shows the totals, the chart and each split, naming what was deleted', async () => {
  await show()
  const text = host.textContent ?? ''
  expect(text).toContain('$1.23')
  expect(host.querySelector('[data-testid="chart"]')).not.toBeNull()
  expect(text).toContain('Billing service')
  expect(text).toContain('Deleted workspace')
  expect(text).toContain('Deleted key')
  expect(text).toContain('No price')
  expect(text).toContain('llama has no known price')
  expect(text).toContain('estimates from public list prices')
  const asked = new URL(urls[0], 'http://x').searchParams
  expect(asked.get('end')).toBe(range('30d').end)
  expect(asked.get('tz')).toBeTruthy()
})

test('changing the period asks again', async () => {
  await show()
  await click([...host.querySelectorAll('button')].find((b) => b.textContent === 'Last month')!)
  await settle()
  expect(new URL(urls.at(-1)!, 'http://x').searchParams.get('start')).toBe(range('last_month').start)
})

test('an empty period says so', async () => {
  answer = () => ok({ ...REPORT, totals: { ...REPORT.totals, turns: 0, cost_micros: 0, unpriced_tokens: 0 }, workspaces: [], models: [], keys: [] })
  await show()
  expect(host.textContent).toContain('No usage in this period')
  expect(host.querySelector('[data-testid="chart"]')).toBeNull()
})

test('a failed load explains and retries', async () => {
  answer = () => refused(400, 'usage_timezone_invalid', 'That time zone is not known.')
  await show()
  expect(host.textContent).toContain('Usage could not be loaded. That time zone is not known.')
  answer = () => ok(REPORT)
  await click([...host.querySelectorAll('button')].find((b) => b.textContent === 'Retry')!)
  await settle()
  expect(host.textContent).toContain('Billing service')
})

test('periods are whole local days ending today', () => {
  const today = new Date(2026, 2, 3)
  expect(range('7d', today)).toEqual({ start: '2026-02-25', end: '2026-03-03' })
  expect(range('month', today)).toEqual({ start: '2026-03-01', end: '2026-03-03' })
  expect(range('last_month', today)).toEqual({ start: '2026-02-01', end: '2026-02-28' })
})

test('money reads as dollars, and a fraction of a cent is not shown as free', () => {
  expect(money(41_250)).toBe('$0.04')
  expect(money(3_000)).toBe('< $0.01')
  expect(money(0)).toBe('$0.00')
  expect(money(12_345_678_900)).toBe('$12,345.68')
})
