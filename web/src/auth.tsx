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

  return <AuthContext.Provider value={{ user, signOut }}>{children}</AuthContext.Provider>
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  if (user === undefined) return null
  if (user === null) return <Navigate to="/signin" replace />
  return children
}
