import DeleteOutlined from '@mui/icons-material/DeleteOutlined'
import {
  Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel,
  IconButton, Radio, RadioGroup, TextField, Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import { PROVIDERS, type Credential, type Provider, type ProviderModel } from '../api/types'
import { ago } from '../format'
import { MONO } from '../theme'

const card = { border: 1, borderColor: 'divider', borderRadius: '12px', bgcolor: 'background.paper' }

function KeyCard({ credential, onDelete }: { credential: Credential; onDelete: () => void }) {
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
    <Box component="article" sx={card}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px 16px', px: 2.5, py: 2 }}>
        <Box sx={{ flex: '1 1 240px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography component="h2" sx={{ fontSize: 15, fontWeight: 600 }}>{credential.label}</Typography>
            <Box component="span" sx={{ px: 1, py: '1px', borderRadius: 999, bgcolor: 'var(--raised)', color: 'text.secondary', fontSize: 12 }}>
              {PROVIDERS[credential.provider]}
            </Box>
          </Box>
          <Typography color="text.secondary" sx={{ fontSize: 13, fontFamily: MONO }}>
            •••• {credential.key_hint}{credential.base_url ? ` · ${credential.base_url}` : ''}
          </Typography>
        </Box>
        <Typography color="text.secondary" sx={{ fontSize: 13 }}>Added {ago(credential.created_at)}</Typography>
        <Button variant="outlined" size="small" aria-expanded={open} onClick={toggle} sx={{ minHeight: 32, borderRadius: '8px', fontWeight: 400 }}>
          Models
        </Button>
        <IconButton aria-label={`Delete ${credential.label}`} onClick={onDelete} sx={{ width: 32, height: 32, border: 1, borderColor: 'divider', borderRadius: '8px' }}>
          <DeleteOutlined fontSize="small" />
        </IconButton>
      </Box>
      {open && (
        <Box sx={{ px: 2.5, pt: 1.5, pb: 2, borderTop: 1, borderColor: 'divider' }}>
          {error ? (
            <Alert severity="error">{error}</Alert>
          ) : !models ? (
            <CircularProgress size={18} />
          ) : models.length === 0 ? (
            <Typography color="text.secondary" sx={{ fontSize: 13 }}>This key lists no models.</Typography>
          ) : (
            <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0, display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              {models.map((m) => (
                <Box component="li" key={m.id} title={m.name} sx={{ px: 1.25, py: 0.5, border: 1, borderColor: 'divider', borderRadius: '6px', fontFamily: MONO, fontSize: 12 }}>
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

function AddKey({ onAdded }: { onAdded: (c: Credential) => void }) {
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
      setLabel('')
      setBaseUrl('')
      setModels('')
    } catch (err) {
      setError(errorText(err))
    } finally {
      // The key leaves the page's state either way; a failed add means typing it again.
      setKey('')
      setBusy(false)
    }
  }

  return (
    <Box component="form" onSubmit={submit} aria-labelledby="add-key" sx={{ ...card, flex: '1 1 340px', p: 2.5, display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Typography id="add-key" component="h2" sx={{ fontSize: 16, fontWeight: 600 }}>Add a key</Typography>
      <Box component="fieldset" sx={{ m: 0, p: 0, border: 0 }}>
        <Typography component="legend" sx={{ fontSize: 13, fontWeight: 500, mb: 1 }}>Provider</Typography>
        <RadioGroup value={provider} onChange={(e) => setProvider(e.target.value as Provider)} sx={{ gap: 1 }}>
          {(Object.keys(PROVIDERS) as Provider[]).map((p) => (
            <FormControlLabel
              key={p}
              value={p}
              control={<Radio size="small" />}
              label={PROVIDERS[p]}
              sx={{
                m: 0, minHeight: 40, pr: 1.5, border: 1, borderRadius: '8px',
                borderColor: provider === p ? 'primary.main' : 'divider',
                bgcolor: provider === p ? 'var(--accentSoft)' : 'transparent',
              }}
            />
          ))}
        </RadioGroup>
      </Box>
      <TextField label="Name" value={label} onChange={(e) => setLabel(e.target.value)} required size="small" placeholder="Work Anthropic" slotProps={{ htmlInput: { maxLength: 100 } }} />
      {custom && (
        <TextField
          label="Base URL"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          required
          size="small"
          placeholder="https://llm.example.com/v1"
          helperText="An https address on the public internet."
          slotProps={{ htmlInput: { maxLength: 500, style: { fontFamily: MONO, fontSize: 13 } } }}
        />
      )}
      {custom && (
        <TextField
          label="Models"
          value={models}
          onChange={(e) => setModels(e.target.value)}
          size="small"
          placeholder="gpt-5.4-mini, another-model"
          helperText="Only if the endpoint has no model list. Separate ids with commas; the key is checked with a short request to the first."
          slotProps={{ htmlInput: { style: { fontFamily: MONO, fontSize: 13 } } }}
        />
      )}
      <TextField label="API key" type="password" value={key} onChange={(e) => setKey(e.target.value)} required size="small" autoComplete="off" slotProps={{ htmlInput: { maxLength: 1000 } }} />
      {error && <Alert severity="error">{error}</Alert>}
      <Button type="submit" variant="contained" disabled={busy} sx={{ minHeight: 44 }}>
        {busy ? 'Checking the key…' : 'Add key'}
      </Button>
    </Box>
  )
}

export function Credentials() {
  const [keys, setKeys] = useState<Credential[] | null>(null)
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState<Credential | null>(null)

  useEffect(() => {
    api<Credential[]>('/api/credentials').then(setKeys, (e) => setError(errorText(e)))
  }, [])

  async function remove(c: Credential) {
    setDeleting(null)
    try {
      await api(`/api/credentials/${c.id}`, { method: 'DELETE' })
      setKeys((all) => all?.filter((k) => k.id !== c.id) ?? null)
    } catch (e) {
      setError(errorText(e))
    }
  }

  return (
    <Box sx={{ minHeight: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box component="main" sx={{ width: '100%', maxWidth: 1120, mx: 'auto', px: 2, py: 6, display: 'flex', flexDirection: 'column', gap: 3 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <Typography component="h1" sx={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.01em' }}>Credentials</Typography>
          <Typography color="text.secondary">Model provider keys, stored encrypted. Your agents use them to think; they never enter an agent's sandbox.</Typography>
        </Box>
        {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
        <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 3 }}>
          <Box component="section" aria-label="Your keys" sx={{ flex: '999 1 520px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            {keys?.length === 0 && (
              <Box sx={{ ...card, p: 3 }}>
                <Typography sx={{ fontWeight: 600 }}>No keys yet</Typography>
                <Typography color="text.secondary">Add a key from a model provider, and your agents can start working.</Typography>
              </Box>
            )}
            {keys?.map((c) => <KeyCard key={c.id} credential={c} onDelete={() => setDeleting(c)} />)}
          </Box>
          <AddKey onAdded={(c) => setKeys((all) => [c, ...(all ?? [])])} />
        </Box>
      </Box>
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
