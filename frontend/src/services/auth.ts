/**
 * Authentication service — uses the FastAPI server-side auth.
 * The JWT token is stored in an httpOnly cookie managed by the server.
 * No client-side token handling needed.
 */

export interface AuthResult {
  success: boolean
  challengeName?: string
  error?: string
}

export interface UserInfo {
  sub: string
  email: string
  username: string
  groups: string[]
}

/**
 * Sign in via the FastAPI server.
 * The server authenticates with Cognito and sets an httpOnly cookie.
 */
export async function signIn(username: string, password: string): Promise<AuthResult> {
  try {
    const response = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ username, password }),
    })

    const data = await response.json()

    if (response.ok && data.success) {
      return { success: true }
    }

    if (data.challengeName) {
      return { success: false, challengeName: data.challengeName }
    }

    return { success: false, error: data.error || 'Authentication failed' }
  } catch (err) {
    return { success: false, error: 'Network error. Please try again.' }
  }
}

/**
 * Sign out — clears the httpOnly cookie on the server.
 */
export async function signOut(): Promise<void> {
  try {
    await fetch('/auth/logout', {
      method: 'POST',
      credentials: 'same-origin',
    })
  } catch {
    // Even if the request fails, consider the user logged out locally
  }
}

/**
 * Get token — returns null because the token is in an httpOnly cookie.
 * It is sent automatically with every request.
 */
export function getToken(): Promise<string | null> {
  return Promise.resolve(null)
}

/**
 * Check if the user is currently authenticated by calling /auth/me.
 */
export async function isAuthenticated(): Promise<boolean> {
  try {
    const response = await fetch('/auth/me', {
      credentials: 'same-origin',
    })
    if (!response.ok) return false
    const data = await response.json()
    return data.authenticated === true
  } catch {
    return false
  }
}

/**
 * Get current user info from the server.
 */
export async function getCurrentUserInfo(): Promise<UserInfo | null> {
  try {
    const response = await fetch('/auth/me', {
      credentials: 'same-origin',
    })
    if (!response.ok) return null
    const data = await response.json()
    if (data.authenticated) {
      return data.user as UserInfo
    }
    return null
  } catch {
    return null
  }
}
