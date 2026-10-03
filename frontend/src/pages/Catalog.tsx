import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Database, Search } from 'lucide-react'
import api from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'

interface CatalogItem {
  id: string
  name: string
  description: string
  owner: string
  tables: number
  created_at: string
}

export default function Catalog() {
  const navigate = useNavigate()
  const [items, setItems] = useState<CatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')

  useEffect(() => {
    loadCatalog()
  }, [])

  const loadCatalog = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.get('/catalog', { params: { limit: 50 } })
      const rawItems = res.data?.items || []
      setItems(rawItems.map((c: any) => ({
        id: c.id || '',
        name: c.name || '',
        description: c.description || '',
        owner: c.owner || '',
        tables: c.tableCount || 0,
        created_at: c.created_at || c.createdAt || '',
      })))
    } catch (err: any) {
      setError(err?.response?.data?.error || err?.message || 'Failed to load catalogs')
      setItems([])
    } finally {
      setLoading(false)
    }
  }

  const filteredItems = items.filter((item) =>
    item.name.toLowerCase().includes(filter.toLowerCase())
  )

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Data Catalog</h1>
          <p className="text-gray-500 text-sm mt-1">Manage catalogs and their tables</p>
        </div>
        <button
          onClick={() => navigate('/upload')}
          className="px-4 py-2 btn-glass-primary text-white rounded-xl text-sm font-medium transition-opacity flex items-center gap-2"
        >
          <Plus className="h-4 w-4" />
          Upload Dataset
        </button>
      </div>

      {/* Search/Filter */}
      <div className="mb-4">
        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Search catalogs..."
            className="w-full pl-10 pr-4 py-2 glass-card rounded-xl text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500"
          />
        </div>
      </div>

      {loading ? (
        <LoadingSpinner message="Loading catalog..." />
      ) : error ? (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-6 text-center">
          <p className="text-sm text-red-700">{error}</p>
          <button onClick={loadCatalog} className="mt-3 text-sm text-violet-700 hover:text-violet-800 font-medium">
            Retry
          </button>
        </div>
      ) : (
        <div className="glass-card rounded-2xl shadow-lg shadow-black/5 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-white/40 bg-white/20">
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Description</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Owner</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
              </tr>
            </thead>
            <tbody>
              {filteredItems.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-6 py-12 text-center text-gray-400">
                    No catalogs found. Upload a dataset to create one.
                  </td>
                </tr>
              ) : (
                filteredItems.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => navigate(`/catalog/${item.id}`)}
                    className="border-b border-white/30 hover:bg-white/30 cursor-pointer transition-colors"
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <Database className="h-4 w-4 text-violet-600" />
                        <p className="text-sm text-gray-900 font-medium">{item.name}</p>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-500 max-w-xs truncate">
                      {item.description || '—'}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-700">{item.owner || '—'}</td>
                    <td className="px-6 py-4 text-sm text-gray-500">
                      {item.created_at ? new Date(item.created_at).toLocaleDateString() : '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
