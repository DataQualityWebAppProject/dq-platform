import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserSession,
} from 'amazon-cognito-identity-js'

const userPool = new CognitoUserPool({
  UserPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
  ClientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
})

export interface AuthResult {
  success: boolean
  session?: CognitoUserSession
  challengeName?: string
  error?: string
}

export function getCurrentUser(): CognitoUser | null {
  return userPool.getCurrentUser()
}

export function getSession(): Promise<CognitoUserSession | null> {
  return new Promise((resolve) => {
    const user = getCurrentUser()
    if (!user) {
      resolve(null)
      return
    }
    user.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session || !session.isValid()) {
        resolve(null)
      } else {
        resolve(session)
      }
    })
  })
}

export function getToken(): Promise<string | null> {
  return getSession().then((session) =>
    session ? session.getIdToken().getJwtToken() : null
  )
}

export function signIn(email: string, password: string): Promise<AuthResult> {
  return new Promise((resolve) => {
    const user = new CognitoUser({ Username: email, Pool: userPool })
    const authDetails = new AuthenticationDetails({
      Username: email,
      Password: password,
    })

    user.authenticateUser(authDetails, {
      onSuccess: (session) => {
        resolve({ success: true, session })
      },
      onFailure: (err) => {
        resolve({ success: false, error: err.message || 'Authentication failed' })
      },
      mfaRequired: () => {
        resolve({ success: false, challengeName: 'SMS_MFA' })
      },
      totpRequired: () => {
        resolve({ success: false, challengeName: 'SOFTWARE_TOKEN_MFA' })
      },
      newPasswordRequired: () => {
        resolve({ success: false, challengeName: 'NEW_PASSWORD_REQUIRED' })
      },
    })
  })
}

export function signOut(): void {
  const user = getCurrentUser()
  if (user) {
    user.signOut()
  }
}

export function isAuthenticated(): Promise<boolean> {
  return getSession().then((session) => session !== null && session.isValid())
}
