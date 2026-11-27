import { Alert, Box, Button, Skeleton, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import { useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { UsageReport, UsageShare } from '../api/types'
import { compact, money } from '../format'

const card = { border: 1, borderColor: 'divider', borderRadius: '12px', bgcolor: 'background.paper' }

export type Period = '7d' | '30d' | 'month' | 'last_month'
const PERIODS: { id: Period; label: string }[] = [
  { id: '7d', label: '7 days' },
  { id: '30d', label: '30 days' },
  { id: 'month', label: 'This month' },
  { id: 'last_month', label: 'Last month' },
]

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/** The inclusive local dates of a period, ending today. */
export function range(period: Period, today = new Date()): { start: string; end: string } {
  const y = today.getFullYear(), m = today.getMonth(), d = today.getDate()
  if (period === 'month') return { start: iso(new Date(y, m, 1)), end: iso(today) }
  if (period === 'last_month') return { start: iso(new Date(y, m - 1, 1)), end: iso(new Date(y, m, 0)) }
  return { start: iso(new Date(y, m, d - (period === '7d' ? 6 : 29))), end: iso(today) }
}

const localDate = (date: string) => new Date(`${date}T00:00`)
const dayLabel = (date: string) => localDate(date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
const tokensOf = (t: UsageReport['totals']) => t.input_tokens + t.output_tokens + t.cache_read_tokens + t.cache_write_tokens

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ ...card, p: 2, flex: '1 1 140px', minWidth: 0 }}>
      <Typography color="text.secondary" sx={{ fontSize: 12 }}>{label}</Typography>
      <Typography sx={{ fontSize: 22, fontWeight: 600, mt: 0.5 }}>{value}</Typography>
    </Box>
  )
}

function Shares({ title, shares, missing }: { title: string; shares: UsageShare[]; missing: string }) {
  if (!shares.length) return null
  return (
    <Box component="section" aria-label={title} sx={{ ...card, p: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Typography component="h2" sx={{ fontSize: 14, fontWeight: 600 }}>{title}</Typography>
      <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0, display: 'flex', flexDirection: 'column', gap: 0.75 }}>
        {shares.map((s) => (
          <Box component="li" key={s.id} sx={{ display: 'flex', alignItems: 'baseline', gap: 1, fontSize: 13, minWidth: 0 }}>
            <Box sx={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: s.name ? 'text.primary' : 'text.secondary' }}>
              {s.name ?? missing}
            </Box>
            <Typography color="text.secondary" sx={{ fontSize: 12, flexShrink: 0 }}>
              {compact(s.tokens)} tokens · {s.turns} {s.turns === 1 ? 'turn' : 'turns'}
            </Typography>
            <Box sx={{ width: 72, textAlign: 'right', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
              {s.cost_micros || !s.unpriced_tokens ? money(s.cost_micros) : 'No price'}
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  )
}

export function Usage() {
  const [period, setPeriod] = useState<Period>('30d')
  const [report, setReport] = useState<UsageReport | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const { start, end } = range(period)
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
    const controller = new AbortController()
    setReport(null)
    setError('')
    api<UsageReport>(`/api/usage?${new URLSearchParams({ start, end, tz })}`, { signal: controller.signal }).then(setReport, (e) => {
      if (!controller.signal.aborted) setError(`Usage could not be loaded. ${errorText(e)}`)
    })
    return () => controller.abort()
  }, [period, attempt])

  const start = range(period).start
  const empty = report !== null && report.totals.turns === 0
  const unpricedModels = report?.models.filter((m) => m.unpriced_tokens).map((m) => m.name) ?? []

  return (
    <Box sx={{ minHeight: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box component="main" sx={{ width: '100%', maxWidth: 760, mx: 'auto', px: 2, py: { xs: 4, md: 6 }, display: 'flex', flexDirection: 'column', gap: 3 }}>
        <Box>
          <Typography component="h1" sx={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.01em' }}>Usage</Typography>
          <Typography color="text.secondary" sx={{ fontSize: 14, mt: 0.5 }}>
            Tokens your turns used on your keys and what they likely cost, counting subagents and side work such as page summaries and memory.
          </Typography>
        </Box>
        <ToggleButtonGroup size="small" exclusive value={period} onChange={(_, p: Period | null) => p && setPeriod(p)} aria-label="Period" sx={{ flexWrap: 'wrap' }}>
          {PERIODS.map((p) => <ToggleButton key={p.id} value={p.id}>{p.label}</ToggleButton>)}
        </ToggleButtonGroup>

        {error && (
          <Alert severity="error" action={<Button color="inherit" size="small" onClick={() => setAttempt((n) => n + 1)}>Retry</Button>}>{error}</Alert>
        )}
        {!report && !error && (
          <Box aria-busy="true" aria-label="Loading usage" sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Box sx={{ display: 'flex', gap: 2 }}>{[0, 1, 2].map((i) => <Skeleton key={i} variant="rounded" height={76} sx={{ flex: 1 }} />)}</Box>
            <Skeleton variant="rounded" height={220} />
          </Box>
        )}
        {empty && (
          <Box sx={{ ...card, p: 4, textAlign: 'center' }}>
            <Typography sx={{ fontWeight: 600 }}>No usage in this period</Typography>
            <Typography color="text.secondary" sx={{ fontSize: 14, mt: 0.5 }}>Turns you run in any workspace show up here with their cost.</Typography>
          </Box>
        )}
        {report && !empty && (
          <>
            <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
              <Stat label="Estimated cost" value={money(report.totals.cost_micros)} />
              <Stat label="Tokens" value={compact(tokensOf(report.totals))} />
              <Stat label="Turns" value={String(report.totals.turns)} />
            </Box>
            <Box component="figure" aria-label="Estimated cost per day" sx={{ ...card, m: 0, p: 2 }}>
              <BarChart
                height={220}
                dataset={report.days.map((d) => ({ day: dayLabel(d.date), dollars: d.cost_micros / 1_000_000 }))}
                xAxis={[{ scaleType: 'band', dataKey: 'day', tickLabelStyle: { fontSize: 11 } }]}
                yAxis={[{ width: 48, valueFormatter: (v: number) => `$${v}` }]}
                series={[{ dataKey: 'dollars', label: 'Estimated cost', valueFormatter: (v) => money(Math.round((v ?? 0) * 1_000_000)) }]}
                hideLegend
                margin={{ left: 0, right: 8, top: 8, bottom: 0 }}
              />
            </Box>
            <Shares title="By workspace" shares={report.workspaces} missing="Deleted workspace" />
            <Shares title="By model" shares={report.models} missing="Unknown model" />
            <Shares title="By key" shares={report.keys} missing="Deleted key" />
          </>
        )}
        {report && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
            {unpricedModels.length > 0 && (
              <Typography color="text.secondary" sx={{ fontSize: 12 }}>
                {unpricedModels.join(', ')} {unpricedModels.length === 1 ? 'has' : 'have'} no known price, so {compact(report.totals.unpriced_tokens)} tokens are left out of the cost.
              </Typography>
            )}
            {report.since && start < report.since.slice(0, 10) && (
              <Typography color="text.secondary" sx={{ fontSize: 12 }}>
                Counting started on {new Date(report.since).toLocaleDateString(undefined, { dateStyle: 'medium' })}; earlier turns are not included.
              </Typography>
            )}
            <Typography color="text.secondary" sx={{ fontSize: 12 }}>
              Costs are estimates from public list prices (updated {localDate(report.prices.fetched).toLocaleDateString(undefined, { dateStyle: 'medium' })}). Your provider's bill is exact: discounts, free tiers and taxes are not in these numbers.
            </Typography>
          </Box>
        )}
      </Box>
    </Box>
  )
}
