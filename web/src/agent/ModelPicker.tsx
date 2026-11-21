import KeyboardArrowDown from '@mui/icons-material/KeyboardArrowDown'
import { Box, Button, Link, Menu, MenuItem, Popover, TextField, Typography } from '@mui/material'
import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router'
import { api, errorText } from '../api/client'
import { PROVIDERS, type Credential, type Effort, type ProviderModel } from '../api/types'

export type ModelChoice = { credentialId: string; model: string }
const EFFORTS: Effort[] = ['auto', 'off', 'low', 'medium', 'high']
const CHOICE = 'echo.model'
const EFFORT = 'echo.effort'

function stored<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function store(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Storage can be refused; the choice then lasts until reload.
  }
}

/** The key, model and effort the next turn runs on. The last choice is remembered in this browser. */
export function useModelChoice() {
  const [keys, setKeys] = useState<Credential[] | null>(null)
  const [choice, setChoiceState] = useState<ModelChoice | null>(() => stored(CHOICE, null))
  const [effort, setEffortState] = useState<Effort>(() => stored(EFFORT, 'auto'))

  useEffect(() => {
    api<Credential[]>('/api/credentials').then(setKeys, () => setKeys([]))
  }, [])

  // A remembered key that has since been deleted is not offered.
  const valid = keys && choice && keys.some((k) => k.id === choice.credentialId) ? choice : null
  return {
    keys,
    choice: valid,
    effort,
    setChoice: (c: ModelChoice) => (setChoiceState(c), store(CHOICE, c)),
    setEffort: (e: Effort) => (setEffortState(e), store(EFFORT, e)),
  }
}

const pill = { minHeight: 32, px: 1.25, borderRadius: '8px', fontSize: 12, fontWeight: 400, borderColor: 'divider', color: 'text.primary' }

export function ModelPicker({ state, disabled }: { state: ReturnType<typeof useModelChoice>; disabled: boolean }) {
  const { keys, choice, effort, setChoice, setEffort } = state
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [effortAnchor, setEffortAnchor] = useState<HTMLElement | null>(null)
  const [keyId, setKeyId] = useState('')
  const [models, setModels] = useState<ProviderModel[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!keyId) return
    setModels(null)
    setError('')
    api<ProviderModel[]>(`/api/credentials/${keyId}/models`).then(setModels, (e) => setError(errorText(e)))
  }, [keyId])

  if (keys && keys.length === 0) {
    return (
      <Typography sx={{ fontSize: 12 }} color="text.secondary">
        <Link component={RouterLink} to="/credentials">Add a model key</Link> to start a chat.
      </Typography>
    )
  }
  const key = keys?.find((k) => k.id === choice?.credentialId)

  return (
    <>
      <Button
        variant="outlined"
        aria-label="Model"
        disabled={disabled || !keys}
        endIcon={<KeyboardArrowDown />}
        onClick={(e) => {
          setAnchor(e.currentTarget)
          setKeyId(choice?.credentialId ?? keys?.[0]?.id ?? '')
        }}
        sx={{ ...pill, maxWidth: 260, minWidth: 0, flexShrink: 1, overflow: 'hidden' }}
      >
        {key && choice ? (
          <Box component="span" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            <Box component="span" sx={{ color: 'text.secondary' }}>{PROVIDERS[key.provider]} ·</Box> {choice.model}
          </Box>
        ) : (
          'Choose a model'
        )}
      </Button>
      <Button variant="outlined" aria-label="Reasoning effort" disabled={disabled} endIcon={<KeyboardArrowDown />} onClick={(e) => setEffortAnchor(e.currentTarget)} sx={{ ...pill, flexShrink: 0 }}>
        <Box component="span" sx={{ color: 'text.secondary', mr: 0.5 }}>Effort</Box> {effort}
      </Button>

      <Popover open={!!anchor} anchorEl={anchor} onClose={() => setAnchor(null)} anchorOrigin={{ vertical: 'top', horizontal: 'left' }} transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}>
        <Box sx={{ p: 2, width: 320, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <TextField select size="small" label="Key" value={keyId} onChange={(e) => setKeyId(e.target.value)}>
            {keys?.map((k) => (
              <MenuItem key={k.id} value={k.id}>{k.label} ({PROVIDERS[k.provider]})</MenuItem>
            ))}
          </TextField>
          {error ? (
            <Typography color="error" sx={{ fontSize: 13 }}>{error}</Typography>
          ) : (
            <TextField
              select
              size="small"
              label="Model"
              disabled={!models}
              value={models?.some((m) => m.id === choice?.model) && keyId === choice?.credentialId ? choice!.model : ''}
              onChange={(e) => {
                setChoice({ credentialId: keyId, model: e.target.value })
                setAnchor(null)
              }}
              helperText={models ? undefined : 'Loading the models this key can use…'}
            >
              {models?.map((m) => (
                <MenuItem key={m.id} value={m.id}>{m.id}</MenuItem>
              ))}
            </TextField>
          )}
        </Box>
      </Popover>
      <Menu open={!!effortAnchor} anchorEl={effortAnchor} onClose={() => setEffortAnchor(null)}>
        {EFFORTS.map((e) => (
          <MenuItem key={e} selected={e === effort} onClick={() => (setEffort(e), setEffortAnchor(null))}>{e}</MenuItem>
        ))}
      </Menu>
    </>
  )
}
