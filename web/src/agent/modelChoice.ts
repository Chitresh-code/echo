import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { api, errorText } from '../api/client'
import { PROVIDERS, type Credential, type Effort, type ProviderModel } from '../api/types'
import { matches, type Command, type CommandOption } from '../composer/commands'

export type ModelChoice = { credentialId: string; model: string }
const EFFORTS: Effort[] = ['auto', 'off', 'low', 'medium', 'high']
const EFFORT_DETAIL: Partial<Record<Effort, string>> = { auto: "The model's own default", off: 'No extra thinking' }
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

/** The api refuses any effort but auto for an OpenAI-compatible endpoint, so it is never offered or sent. */
const autoOnly = (key: Credential | undefined) => key?.provider === 'openai_compatible'

/**
 * The key, model and effort the next turn runs on, and the `/model` and `/effort` commands that
 * change them. The last choice is remembered in this browser for every workspace.
 */
export function useModelChoice() {
  const navigate = useNavigate()
  const [keys, setKeys] = useState<Credential[] | null>(null)
  const [loadError, setLoadError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [choice, setChoiceState] = useState<ModelChoice | null>(() => stored(CHOICE, null))
  const [picked, setEffortState] = useState<Effort>(() => stored(EFFORT, 'auto'))
  // Each key's models, by key id; missing means still loading. Asked for only once a menu opens,
  // since listing them calls the provider.
  const [models, setModels] = useState<Record<string, ProviderModel[] | { error: string }>>({})
  const [wanted, setWanted] = useState(false)
  const loading = useRef(new Set<string>())

  // A failed load is not "no keys": it says so and can be retried, instead of asking to add one.
  useEffect(() => {
    setLoadError('')
    api<Credential[]>('/api/credentials').then(setKeys, (e) => setLoadError(errorText(e)))
  }, [attempt])

  useEffect(() => {
    if (!wanted || !keys) return
    for (const k of keys) {
      if (models[k.id] || loading.current.has(k.id)) continue
      loading.current.add(k.id)
      api<ProviderModel[]>(`/api/credentials/${k.id}/models`)
        .then(
          (list) => setModels((m) => ({ ...m, [k.id]: list })),
          (e) => setModels((m) => ({ ...m, [k.id]: { error: errorText(e) } })),
        )
        .finally(() => loading.current.delete(k.id))
    }
  }, [wanted, keys, models])

  // A remembered key that has since been deleted is not offered.
  const valid = keys && choice && keys.some((k) => k.id === choice.credentialId) ? choice : null
  const key = keys?.find((k) => k.id === valid?.credentialId)
  const effort: Effort = autoOnly(key) ? 'auto' : picked

  const setChoice = (c: ModelChoice) => (setChoiceState(c), store(CHOICE, c))
  const setEffort = (e: Effort) => (setEffortState(e), store(EFFORT, e))
  const want = () => {
    if (!wanted) queueMicrotask(() => setWanted(true))
  }

  const modelCommand: Command = {
    name: 'model',
    description: 'Choose the model for the next message',
    options(query) {
      if (loadError) return [{ id: 'keys', label: 'Retry', detail: `Your model keys did not load. ${loadError}` }]
      if (!keys) return [{ id: 'wait', label: 'Loading your keys', disabled: true }]
      if (!keys.length) return [{ id: 'credentials', label: 'Add a model key', detail: 'Opens Credentials' }]
      want()
      return keys.flatMap((k): CommandOption[] => {
        const group = `${k.label} · ${PROVIDERS[k.provider]}`
        const list = models[k.id]
        if (!list) return [{ id: `wait:${k.id}`, label: 'Loading the models', group, disabled: true }]
        // A failed key is shown until a filter is typed, so Enter on `/model mini` picks a model, not Retry.
        if ('error' in list) return query.trim() ? [] : [{ id: `retry:${k.id}`, label: 'Retry', detail: list.error, group }]
        return list
          .filter((m) => matches(m.id, query))
          .map((m) => ({ id: `model:${k.id}:${m.id}`, label: m.id, group, selected: valid?.credentialId === k.id && valid.model === m.id }))
      })
    },
    apply(option) {
      if (option.id === 'keys') return (setAttempt((n) => n + 1), null)
      if (option.id === 'credentials') return (navigate('/credentials'), 'Opening Credentials')
      if (option.id.startsWith('retry:')) {
        const id = option.id.slice('retry:'.length)
        setModels(({ [id]: _, ...rest }) => rest)
        return null
      }
      const rest = option.id.slice('model:'.length)
      const credentialId = rest.slice(0, rest.indexOf(':'))
      setChoice({ credentialId, model: option.label })
      if (autoOnly(keys?.find((k) => k.id === credentialId)) && picked !== 'auto') {
        setEffort('auto')
        return `Model set to ${option.label}. Effort set to auto, the only level this key's service takes.`
      }
      return `Model set to ${option.label}`
    },
  }

  const effortCommand: Command = {
    name: 'effort',
    description: 'How hard the model thinks before it answers',
    options: (query) =>
      (autoOnly(key) ? (['auto'] as Effort[]) : EFFORTS)
        .filter((e) => matches(e, query))
        .map((e) => ({
          id: e,
          label: e,
          group: 'Effort',
          detail: autoOnly(key) ? "The only level this key's service takes" : EFFORT_DETAIL[e],
          selected: e === effort,
        })),
    apply(option) {
      setEffort(option.id as Effort)
      return `Effort set to ${option.id}`
    },
  }

  return {
    keys,
    loadError,
    retry: () => setAttempt((n) => n + 1),
    choice: valid,
    /** What the next turn sends: auto for a key whose service takes nothing else. */
    effort,
    commands: [modelCommand, effortCommand],
  }
}

export type ModelState = ReturnType<typeof useModelChoice>
