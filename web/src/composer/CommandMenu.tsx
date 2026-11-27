import Check from '@mui/icons-material/Check'
import { Box, Typography } from '@mui/material'
import { useEffect } from 'react'
import type { CommandOption } from './commands'

type Props = {
  id: string
  label: string
  rows: CommandOption[]
  active: number
  onPick: (index: number) => void
  onHover: (index: number) => void
  /** Shown when there are no rows. */
  empty?: string
}

/**
 * The list behind `/` and the settings label. Focus stays in the text box or search field, which
 * points at the active row with aria-activedescendant, so typing keeps filtering.
 */
export function CommandMenu({ id, label, rows, active, onPick, onHover, empty }: Props) {
  useEffect(() => {
    document.getElementById(`${id}-${active}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [id, active])

  // Consecutive rows of one group become one labelled group, so a screen reader names it.
  const sections: { group?: string; start: number; rows: CommandOption[] }[] = []
  rows.forEach((row, i) => {
    const last = sections[sections.length - 1]
    if (last && last.group === row.group) last.rows.push(row)
    else sections.push({ group: row.group, start: i, rows: [row] })
  })

  return (
    <Box role="listbox" id={id} aria-label={label} sx={{ maxHeight: 320, overflowY: 'auto', py: 0.5 }}>
      {sections.map((s) => (
        <Box key={s.start} role={s.group ? 'group' : undefined} aria-labelledby={s.group ? `${id}-g${s.start}` : undefined}>
          {s.group && (
            <Typography id={`${id}-g${s.start}`} sx={{ px: 1.5, pt: 1, pb: 0.5, fontSize: 12, fontWeight: 600, color: 'text.secondary' }}>
              {s.group}
            </Typography>
          )}
          {s.rows.map((row, j) => {
            const i = s.start + j
            return (
              <Box
                key={row.id}
                id={`${id}-${i}`}
                role="option"
                aria-selected={i === active}
                aria-disabled={row.disabled || undefined}
                // Keeps focus in the text box, so the menu never closes under the pointer.
                onMouseDown={(e) => e.preventDefault()}
                onMouseMove={() => i !== active && onHover(i)}
                onClick={() => onPick(i)}
                sx={{
                  display: 'flex', alignItems: 'baseline', gap: 1, px: 1.5, py: 0.75, mx: 0.5, borderRadius: '6px', fontSize: 14,
                  cursor: row.disabled ? 'default' : 'pointer', color: row.disabled ? 'text.secondary' : 'text.primary',
                  bgcolor: i === active ? 'action.selected' : 'transparent',
                }}
              >
                <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 0, maxWidth: '70%' }}>{row.label}</Box>
                {row.detail && (
                  <Box component="span" sx={{ fontSize: 12, color: 'text.secondary', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{row.detail}</Box>
                )}
                {row.selected && <Check titleAccess="In use" sx={{ ml: 'auto', fontSize: 16, alignSelf: 'center', color: 'primary.main' }} />}
              </Box>
            )
          })}
        </Box>
      ))}
      {rows.length === 0 && empty && <Typography sx={{ px: 1.5, py: 1, fontSize: 13 }} color="text.secondary">{empty}</Typography>}
    </Box>
  )
}
