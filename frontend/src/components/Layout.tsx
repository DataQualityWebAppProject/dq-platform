import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
  LayoutDashboard,
  Database,
  Ruler,
  CheckCircle2,
  AlertTriangle,
  Sparkles,
  FileText,
  Settings,
  LogOut,
  Upload,
} from 'lucide-react'

const navItems = [
  { path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/catalog', label: 'Catalog', icon: Database },
  { path: '/upload', label: 'Upload', icon: Upload },
  { path: '/rules', label: 'Rules', icon: Ruler },
  { path: '/validation', label: 'Validation', icon: CheckCircle2 },
  { path: '/anomalies', label: 'Anomalies', icon: AlertTriangle },
  { path: '/cleaning', label: 'Cleaning', icon: Sparkles },
  { path: '/reports', label: 'Reports', icon: FileText },
  { path: '/settings', label: 'Settings', icon: Settings },
]

export default function Layout() {
  const { logout } = useAuth()

  return (
    <div className="flex h-screen app-bg">
      {/* Sidebar - deep amethyst glass */}
      <aside className="w-64 glass-sidebar flex flex-col shrink-0 z-10">
        <div className="p-6 border-b border-white/10">
          <h1 className="text-xl font-bold text-violet-300">DQ Platform</h1>
          <p className="text-xs text-slate-400 mt-1">Data Quality Management</p>
        </div>
        <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
          {navItems.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm transition-colors ${
                    isActive
                      ? 'glass-nav-active text-white font-medium'
                      : 'text-slate-200 hover:bg-white/5 hover:text-white'
                  }`
                }
              >
                <Icon className="h-4 w-4" />
                <span>{item.label}</span>
              </NavLink>
            )
          })}
        </nav>
        <div className="p-4 border-t border-white/10">
          <button
            onClick={logout}
            className="w-full flex items-center gap-3 px-4 py-2 text-sm text-red-400 hover:bg-red-900/20 rounded-xl transition-colors"
          >
            <LogOut className="h-4 w-4" />
            Sign Out
          </button>
        </div>
      </aside>

      {/* Main content - sits above the color blobs */}
      <main className="flex-1 overflow-y-auto relative z-10">
        <Outlet />
      </main>
    </div>
  )
}
