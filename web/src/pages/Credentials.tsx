import Add from '@mui/icons-material/Add'
import DeleteOutlined from '@mui/icons-material/DeleteOutlined'
import ExpandMore from '@mui/icons-material/ExpandMore'
import KeyOutlined from '@mui/icons-material/KeyOutlined'
import {
  Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle,
  IconButton, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import { PROVIDERS, type Credential, type Provider, type ProviderModel } from '../api/types'
import { ago } from '../format'
import { MONO } from '../theme'

const card = { border: 1, borderColor: 'divider', borderRadius: '12px', bgcolor: 'background.paper' }

function KeyRow({ credential, onDelete }: { credential: Credential; onDelete: () => void }) {
  const [open, setOpen] = useState(false)
  const [models, setModels] = useState<ProviderModel[] | null>(null)
  const [error, setError] = useState('')

  function toggle() {
    setOpen(!open)
    if (!open && !models) {
      api<ProviderModel[]>(`/api/credentials/${credential.id}/models`).then(setModels, (e) => setError(errorText(e)))
    }
  }

  return (
    <Box component="li" sx={{ '& + &': { borderTop: 1, borderColor: 'divider' } }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, px: 2, py: 1.5 }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
            <Typography component="h3" noWrap sx={{ fontSize: 14, fontWeight: 600 }}>{credential.label}</Typography>
            <Box component="span" sx={{ px: 1, py: '1px', borderRadius: 999, bgcolor: 'var(--raised)', color: 'text.secondary', fontSize: 12, flexShrink: 0 }}>
              {PROVIDERS[credential.provider]}
            </Box>
          </Box>
          <Typography color="text.secondary" noWrap title={credential.base_url ?? undefined} sx={{ fontSize: 12, mt: 0.25 }}>
            <Box component="span" sx={{ fontFamily: MONO }}>•••• {credential.key_hint}</Box>
            {' · '}Added {ago(credential.created_at)}
            {credential.base_url && <>{' · '}<Box component="span" sx={{ fontFamily: MONO }}>{host(credential.base_url)}</Box></>}
          </Typography>
        </Box>
        <Button size="small" aria-expanded={open} onClick={toggle} endIcon={<ExpandMore sx={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }} />} sx={{ fontWeight: 400, color: 'text.secondary' }}>
          Models
        </Button>
        <Tooltip title="Delete key">
          <IconButton aria-label={`Delete ${credential.label}`} onClick={onDelete} size="small">
            <DeleteOutlined fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
      {open && (
        <Box sx={{ px: 2, pb: 1.5 }}>
          {error ? (
            <Alert severity="error">{error}</Alert>
          ) : !models ? (
            <CircularProgress size={16} aria-label="Loading models" />
          ) : models.length === 0 ? (
            <Typography color="text.secondary" sx={{ fontSize: 13 }}>This key lists no models.</Typography>
          ) : (
            <Box component="ul" aria-label={`Models for ${credential.label}`} sx={{ listStyle: 'none', m: 0, p: 0, display: 'flex', flexWrap: 'wrap', gap: 0.75, maxHeight: 160, overflowY: 'auto' }}>
              {models.map((m) => (
                <Box component="li" key={m.id} title={m.name} sx={{ px: 1, py: 0.25, borderRadius: '6px', bgcolor: 'var(--raised)', fontFamily: MONO, fontSize: 12 }}>
                  {m.id}
                </Box>
              ))}
            </Box>
          )}
        </Box>
      )}
    </Box>
  )
}

function host(url: string) {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

/** Fields carry names and autocomplete hints that keep browsers and password managers from filling
 *  the signed-in email or a saved password into them. */
const noFill = { autoComplete: 'off', 'data-1p-ignore': true, 'data-lpignore': 'true', 'data-form-type': 'other' }

function AddKey({ onClose, onAdded }: { onClose: () => void; onAdded: (c: Credential) => void }) {
  const [provider, setProvider] = useState<Provider>('anthropic')
  const [label, setLabel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [models, setModels] = useState('')
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const custom = provider === 'openai_compatible'

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const ids = models.split(/[\s,]+/).filter(Boolean)
      const body = {
        provider, label: label.trim(), api_key: key,
        base_url: custom ? baseUrl.trim() : null,
        models: custom && ids.length ? ids : null,
      }
      onAdded(await api<Credential>('/api/credentials', { method: 'POST', body }))
    } catch (err) {
      setError(errorText(err))
      // The key leaves the page's state on failure; a retry means typing it again.
      setKey('')
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={busy ? undefined : onClose} fullWidth maxWidth="xs" slotProps={{ paper: { component: 'form', onSubmit: submit, autoComplete: 'off' } as object }}>
      <DialogTitle>Add a key</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2.5, pt: '8px !important' }}>
        <Box>
          <Typography id="provider-label" sx={{ fontSize: 13, fontWeight: 500, mb: 1 }}>Provider</Typography>
          <ToggleButtonGroup
            aria-labelledby="provider-label"
            exclusive
            value={provider}
            onChange={(_, p: Provider | null) => p && setProvider(p)}
            sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, '& .MuiToggleButtonGroup-grouped': { border: 1, borderColor: 'divider', borderRadius: '8px !important', m: '0 !important' } }}
          >
            {(Object.keys(PROVIDERS) as Provider[]).map((p) => (
              <ToggleButton key={p} value={p} size="small" sx={{ textTransform: 'none', justifyContent: 'flex-start', px: 1.5, fontSize: 13, '&.Mui-selected': { borderColor: 'primary.main', bgcolor: 'var(--accentSoft)' } }}>
                {PROVIDERS[p]}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Box>
        <TextField label="Name" name="echo-key-name" value={label} onChange={(e) => setLabel(e.target.value)} required size="small" placeholder="Work Anthropic" autoFocus slotProps={{ htmlInput: { maxLength: 100, ...noFill } }} />
        {custom && (
          <TextField
            label="Base URL"
            name="echo-key-base-url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            required
            size="small"
            placeholder="https://llm.example.com/v1"
            helperText="An https address on the public internet."
            slotProps={{ htmlInput: { maxLength: 500, ...noFill, style: { fontFamily: MONO, fontSize: 13 } } }}
          />
        )}
        {custom && (
          <TextField
            label="Models"
            name="echo-key-models"
            value={models}
            onChange={(e) => setModels(e.target.value)}
            size="small"
            placeholder="gpt-5.4-mini, another-model"
            helperText="Only if the endpoint has no model list. Separate ids with commas; the key is checked with a short request to the first."
            slotProps={{ htmlInput: { ...noFill, style: { fontFamily: MONO, fontSize: 13 } } }}
          />
        )}
        <TextField
          label="API key"
          name="echo-provider-key"
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          required
          size="small"
          helperText="Checked with the provider before it is saved."
          slotProps={{ htmlInput: { maxLength: 1000, ...noFill, autoComplete: 'new-password', style: { fontFamily: MONO } } }}
        />
        {error && <Alert severity="error">{error}</Alert>}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2.5 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? 'Checking the key…' : 'Add key'}</Button>
      </DialogActions>
    </Dialog>
  )
}

export function Credentials() {
  const [keys, setKeys] = useState<Credential[] | null>(null)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [adding, setAdding] = useState(false)
  const [deleting, setDeleting] = useState<Credential | null>(null)

  function load() {
    setLoadError('')
    api<Credential[]>('/api/credentials').then(setKeys, (e) => setLoadError(errorText(e)))
  }

  useEffect(load, [])

  async function remove(c: Credential) {
    setDeleting(null)
    try {
      await api(`/api/credentials/${c.id}`, { method: 'DELETE' })
      setKeys((all) => all?.filter((k) => k.id !== c.id) ?? null)
    } catch (e) {
      setError(errorText(e))
    }
  }

  const addButton = <Button variant="contained" startIcon={<Add />} onClick={() => setAdding(true)} sx={{ flexShrink: 0 }}>Add key</Button>

  return (
    <Box sx={{ minHeight: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box component="main" sx={{ width: '100%', maxWidth: 760, mx: 'auto', px: 2, py: { xs: 4, md: 6 }, display: 'flex', flexDirection: 'column', gap: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap' }}>
          <Box sx={{ flex: '1 1 320px' }}>
            <Typography component="h1" sx={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.01em' }}>Credentials</Typography>
            <Typography color="text.secondary" sx={{ fontSize: 14, mt: 0.5 }}>Model provider keys, stored encrypted. Your agents use them to think; they never enter an agent's sandbox.</Typography>
          </Box>
          {keys && keys.length > 0 && addButton}
        </Box>
        {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
        {loadError ? (
          <Alert severity="error" action={<Button size="small" onClick={load}>Retry</Button>}>Your keys could not be loaded. {loadError}</Alert>
        ) : keys === null ? (
          <Box role="status" aria-label="Loading keys" sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress size={20} /></Box>
        ) : keys.length === 0 ? (
          <Box sx={{ ...card, p: 4, display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 1.5 }}>
            <KeyOutlined sx={{ fontSize: 28, color: 'text.secondary' }} />
            <Box>
              <Typography sx={{ fontWeight: 600 }}>No keys yet</Typography>
              <Typography color="text.secondary" sx={{ fontSize: 14 }}>Add a key from a model provider, and your agents can start working.</Typography>
            </Box>
            {addButton}
          </Box>
        ) : (
          <Box component="section" aria-labelledby="your-keys" sx={card}>
            <Typography id="your-keys" component="h2" sx={{ fontSize: 13, fontWeight: 600, color: 'text.secondary', px: 2, pt: 1.5, pb: 0.5 }}>
              {keys.length === 1 ? '1 key' : `${keys.length} keys`}
            </Typography>
            <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0 }}>
              {keys.map((c) => <KeyRow key={c.id} credential={c} onDelete={() => setDeleting(c)} />)}
            </Box>
          </Box>
        )}
      </Box>
      {adding && (
        <AddKey
          onClose={() => setAdding(false)}
          onAdded={(c) => {
            setKeys((all) => [c, ...(all ?? [])])
            setAdding(false)
          }}
        />
      )}
      {deleting && (
        <Dialog open onClose={() => setDeleting(null)}>
          <DialogTitle>Delete {deleting.label}?</DialogTitle>
          <DialogContent>
            <Typography color="text.secondary">Chats that use this key stop working until you pick another one.</Typography>
          </DialogContent>
          <DialogActions sx={{ px: 3, pb: 2 }}>
            <Button onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="contained" color="error" onClick={() => remove(deleting)}>Delete</Button>
          </DialogActions>
        </Dialog>
      )}
    </Box>
  )
}
