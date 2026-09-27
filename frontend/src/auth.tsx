import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, session, type User } from './api'

interface AuthState {
  user: User | null
  login: (username: string, password: string) => Promise<User>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => session.user)

  useEffect(() => {
    const onLogout = () => setUser(null)
    window.addEventListener('webook:logout', onLogout)
    return () => window.removeEventListener('webook:logout', onLogout)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const r = await api.login(username, password)
    session.save(r.access, r.refresh, r.user)
    setUser(r.user)
    return r.user
  }, [])

  const logout = useCallback(() => {
    session.clear()
    setUser(null)
  }, [])

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside AuthProvider')
  return ctx
}
