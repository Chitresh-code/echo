import { Box, ButtonBase, Link, Popover, TextField, Tooltip, Typography } from '@mui/material'
import { useId, useState } from 'react'
import { Link as RouterLink } from 'react-router'
import type { ModelState } from '../agent/modelChoice'
import { CommandMenu } from './CommandMenu'
import { step, type Command, type CommandOption } from './commands'

// Read by screen readers only.
const visuallyHidden = { position: 'absolute', width: '1px', height: '1px', overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap' } as const

/**
 * The model and effort the next message uses, as a quiet line in the corner of the message box,
 * with "yolo" after them when the workspace runs tools without asking.
 * Clicking it opens every command's options with a search field, for anyone who does not know
 * about `/` or is on a touch screen.
 */
export function SettingsLabel({ state, yolo = false }: { state: ModelState; yolo?: boolean }) {
  const { keys, loadError, retry, choice, effort, commands } = state
  const listId = useId()
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [search, setSearch] = useState('')
  // null: the first row that can be picked.
  const [active, setActive] = useState<number | null>(null)
  const [said, setSaid] = useState('')

  if (loadError) {
    return (
      <Typography sx={{ fontSize: 12, px: 1 }} color="error">
        Your model keys did not load. {loadError}{' '}
        <Link component="button" type="button" onClick={retry} sx={{ fontSize: 12 }}>Retry</Link>
      </Typography>
    )
  }
  if (keys && keys.length === 0) {
    return (
      <Typography sx={{ fontSize: 12, px: 1 }} color="text.secondary">
        <Link component={RouterLink} to="/credentials">Add a model key</Link> to start a chat.
      </Typography>
    )
  }

  // Ids are prefixed with the command, since two commands may both have a row called "auto".
  const entries: { command: Command; option: CommandOption }[] = anchor
    ? commands.flatMap((command) => command.options(search).map((option) => ({ command, option })))
    : []
  const rows = entries.map(({ command, option }) => ({ ...option, id: `${command.name}/${option.id}` }))
  const at = Math.min(active ?? Math.max(rows.findIndex((r) => !r.disabled), 0), Math.max(rows.length - 1, 0))

  function pick(index: number) {
    const entry = entries[index]
    if (!entry || entry.option.disabled) return
    const line = entry.command.apply(entry.option)
    if (line === null) return
    setSaid(line)
    setAnchor(null)
  }

  const text = (choice ? choice.model + (effort === 'auto' ? '' : ` · ${effort}`) : 'Choose a model') + (yolo ? ' · yolo' : '')
  return (
    <>
      <Tooltip title={`Change with ${commands.map((c) => `/${c.name}`).join(', ')}`} describeChild>
        <ButtonBase
          aria-label={`Model ${choice?.model ?? 'not chosen'}, effort ${effort}${yolo ? ', tools run without asking' : ''}. Change`}
          aria-haspopup="dialog"
          disabled={!keys}
          onClick={(e) => {
            setSearch('')
            setActive(null)
            setSaid('')
            setAnchor(e.currentTarget)
          }}
          sx={{
            maxWidth: '100%', minHeight: 32, px: 1, borderRadius: '6px', fontSize: 12, justifyContent: 'flex-start',
            color: choice ? 'text.secondary' : 'primary.main', '&:hover, &.Mui-focusVisible': { bgcolor: 'action.hover', color: 'text.primary' },
          }}
        >
          <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{keys ? text : 'Loading your keys…'}</Box>
        </ButtonBase>
      </Tooltip>
      <Box role="status" sx={visuallyHidden}>{said}</Box>
      <Popover
        open={!!anchor}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
        transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        slotProps={{ paper: { role: 'dialog', 'aria-label': 'Model and effort', sx: { width: 340, maxWidth: 'calc(100vw - 32px)', borderRadius: '10px' } } }}
      >
        <Box sx={{ p: 1, pb: 0 }}>
          <TextField
            autoFocus
            fullWidth
            size="small"
            placeholder="Search models and effort"
            value={search}
            onChange={(e) => (setSearch(e.target.value), setActive(null))}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault()
                setActive(step(rows.length, at, e.key === 'ArrowDown' ? 1 : -1))
              } else if (e.key === 'Enter') {
                e.preventDefault()
                pick(at)
              }
            }}
            slotProps={{
              htmlInput: {
                'aria-label': 'Search models and effort',
                'aria-controls': listId,
                'aria-activedescendant': rows.length ? `${listId}-${at}` : undefined,
              },
            }}
          />
        </Box>
        <CommandMenu id={listId} label="Model and effort" rows={rows} active={at} onPick={pick} onHover={setActive} empty={`Nothing matches "${search}".`} />
      </Popover>
    </>
  )
}
