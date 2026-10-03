import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ShieldCheck, Lock, Mail } from 'lucide-react'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [challenge, setChallenge] = useState<string | null>(null)
  const { login } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    const result = await login(email, password)
    setLoading(false)

    if (result.success) {
      navigate('/dashboard')
    } else if (result.challengeName) {
      setChallenge(result.challengeName)
      setError(`Challenge required: ${result.challengeName}`)
    } else {
      setError(result.error || 'Login failed')
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden" style={{ background: 'linear-gradient(180deg, #020617 0%, #1e1b4b 100%)' }}>
      {/* Vivid blurred color blobs behind the glass */}
      <div className="absolute w-[500px] h-[500px] rounded-full opacity-40 -top-24 -left-24" style={{ background: '#9333ea', filter: 'blur(100px)' }} />
      <div className="absolute w-[500px] h-[500px] rounded-full opacity-40 -bottom-24 -right-24" style={{ background: '#6d28d9', filter: 'blur(100px)' }} />

      <div className="max-w-md w-full space-y-8 relative z-10">
        {/* Logo / Branding */}
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl mb-4 glass-nav-active">
            <ShieldCheck className="h-8 w-8 text-violet-300" />
          </div>
          <h1 className="text-3xl font-bold text-violet-200">DQ Platform</h1>
          <p className="mt-2 text-slate-400">Data Quality Management System</p>
        </div>

        <form onSubmit={handleSubmit} className="glass-sidebar rounded-2xl p-8 space-y-6 shadow-2xl shadow-black/30">
          <h2 className="text-xl font-semibold text-white text-center">Sign In</h2>

          {error && (
            <div className="bg-red-900/30 border border-red-700 text-red-300 p-3 rounded-lg text-sm">
              {error}
            </div>
          )}

          {challenge && (
            <div className="bg-yellow-900/30 border border-yellow-700 text-yellow-300 p-3 rounded-lg text-sm">
              MFA verification required. Please complete the challenge in your authenticator app.
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Username</label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <input
                type="text"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="username"
                className="w-full pl-10 pr-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent"
                placeholder="admindatos"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Password</label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full pl-10 pr-4 py-2.5 bg-white/5 border border-white/10 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent"
                placeholder="••••••••"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 px-4 btn-glass-primary disabled:opacity-50 text-white font-medium rounded-xl transition-opacity"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Signing in...
              </span>
            ) : (
              'Sign In'
            )}
          </button>

          <p className="text-center text-xs text-slate-500">
            Protected by AWS Cognito with MFA
          </p>
        </form>
      </div>
    </div>
  )
}
