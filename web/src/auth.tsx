import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { Navigate } from 'react-router'
import { api, setUnauthorizedHandler } from './api/client'
import type { User } from './api/types'

type Auth = { user: User | null | undefined; signOut: () => Promise<void> }

const AuthContext = createContext<Auth>({ user: undefined, signOut: async () => {} })

export const useAuth = () => useContext(AuthContext)

/** Who is signed in: undefined while loading, null when nobody is. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined)

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    api<User>('/api/auth/me').then(setUser, () => setUser(null))
  }, [])

  const signOut = useCallback(async () => {
    await api('/api/auth/logout', { method: 'POST' }).catch(() => {})
    setUser(null)
  }, [])

  // After sign out, once the message boxes have closed: closing saves their last text as a draft.
  useEffect(() => {
    if (user === null) clearDrafts()
  }, [user])

  return <AuthContext.Provider value={{ user, signOut }}>{children}</AuthContext.Provider>
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  if (user === undefined) return null
  if (user === null) return <Navigate to="/signin" replace />
  return children
}

export const DRAFT_PREFIX = 'echo.draft.'

/** Unsent messages are kept per tab while typing; the next person at this browser must not see them. */
function clearDrafts() {
  try {
    for (const key of Object.keys(sessionStorage)) if (key.startsWith(DRAFT_PREFIX)) sessionStorage.removeItem(key)
  } catch {
    // Storage refused (private mode): nothing was saved either.
  }
}
