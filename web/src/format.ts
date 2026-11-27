/** "4 min ago", "yesterday", "Nov 18": how long ago something happened, as the lists show it. */
export function ago(iso: string, now = new Date()): string {
  const then = new Date(iso)
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  if (minutes < 24 * 60 && then.getDate() === now.getDate()) return `${Math.floor(minutes / 60)} h ago`
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (then.toDateString() === yesterday.toDateString()) return 'yesterday'
  const sameYear = then.getFullYear() === now.getFullYear()
  return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: sameYear ? undefined : 'numeric' })
}

/** 21300 -> "21.3k", for token counts. */
export function compact(n: number): string {
  return n < 1000 ? String(n) : `${(n / 1000).toFixed(n < 10000 ? 1 : 0).replace(/\.0$/, '')}k`
}

/** 1288490188 -> "1.2 GB": disk sizes as the Files tab shows them. */
export function bytes(n: number): string {
  const units = ['bytes', 'KB', 'MB', 'GB']
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return i === 0 ? `${n} bytes` : `${n.toFixed(n < 10 ? 1 : 0).replace(/\.0$/, '')} ${units[i]}`
}

/** How full an agent's storage is: over the limit nothing can be written, near it a warning. */
export function storageLevel(used: number, limit: number): 'ok' | 'warning' | 'error' {
  return used > limit ? 'error' : used >= limit * 0.9 ? 'warning' : 'ok'
}

/** 41_250 micros -> "$0.04", 3_000 -> "< $0.01": an estimated cost as the app shows it. */
export function money(micros: number): string {
  if (micros > 0 && micros < 5_000) return '< $0.01'
  return (micros / 1_000_000).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}
