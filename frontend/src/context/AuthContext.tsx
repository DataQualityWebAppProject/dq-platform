import React, { createContext, useContext, useState, useEffect } from 'react'
import { isAuthenticated, signIn, signOut, AuthResult } from '../services/auth'

interface AuthContextType {
  authenticated: boolean
  loading: boolean
  login: (email: string, password: string) => Promise<AuthResult>
  logout: () => void
}

const AuthContext = createContext<AuthContextType>({
  authenticated: false,
  loading: true,
  login: async () => ({ success: false }),
  logout: () => {},
})

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    isAuthenticated().then((authed) => {
      setAuthenticated(authed)
      setLoading(false)
    })
  }, [])

  const login = async (email: string, password: string): Promise<AuthResult> => {
    const result = await signIn(email, password)
    if (result.success) {
      setAuthenticated(true)
    }
    return result
  }

  const logout = () => {
    signOut()
    setAuthenticated(false)
  }

  return (
    <AuthContext.Provider value={{ authenticated, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
