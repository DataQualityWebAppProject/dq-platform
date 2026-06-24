import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Database, Search } from 'lucide-react'
import api from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'

interface CatalogItem {
  id: string
  name: string
  source: string
  type: string
  status: string
  tables: number
  updated_at: string
}

export default function Catalog() {
  const navigate = useNavigate()
  const [items, setItems] = useState<CatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    loadCatalog()
  }, [page])

  const loadCatalog = async () => {
    setLoading(true)
    try {
      const res = await api.get('/governance/catalog', { params: { page, limit: 10 } })
      setItems(res.data.items || [])
    } catch {
      // Demo data fallback when API isn't ready
      setItems([
        { id: '1', name: 'Production PostgreSQL', source: 'postgresql://prod-db', type: 'PostgreSQL', status: 'connected', tables: 12, updated_at: '2025-01-15' },
        { id: '2', name: 'Analytics S3 Bucket', source: 's3://analytics-data', type: 'S3', status: 'connected', tables: 8, updated_at: '2025-01-14' },
        { id: '3', name: 'Customer DynamoDB', source: 'dynamodb://customers', type: 'DynamoDB', status: 'connected', tables: 5, updated_at: '2025-01-14' },
        { id: '4', name: 'Legacy MySQL', source: 'mysql://legacy-db', type: 'MySQL', status: 'disconnected', tables: 23, updated_at: '2025-01-10' },
      ])
    } finally {
      setLoading(false)
    }
  }

  const filteredItems = items.filter((item) =>
    item.name.toLowerCase().includes(filter.toLowerCase()) ||
    item.type.toLowerCase().includes(filter.toLowerCase())
  )

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Data Catalog</h1>
          <p className="text-gray-400 text-sm mt-1">Manage data sources, tables, and fields</p>
        </div>
        <button className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-2">
          <Plus className="h-4 w-4" />
          Register Source
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
            placeholder="Search sources..."
            className="w-full pl-10 pr-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      {loading ? (
        <LoadingSpinner message="Loading catalog..." />
      ) : (
        <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-700">
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Name</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Type</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Tables</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Status</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Updated</th>
              </tr>
            </thead>
            <tbody>
              {filteredItems.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-gray-500">
                    No catalog entries found. Register a data source to get started.
                  </td>
                </tr>
              ) : (
                filteredItems.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => navigate(`/catalog/${item.id}`)}
                    className="border-b border-gray-700/50 hover:bg-gray-700/30 cursor-pointer"
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <Database className="h-4 w-4 text-blue-400" />
                        <div>
                          <p className="text-sm text-white font-medium">{item.name}</p>
                          <p className="text-xs text-gray-500">{item.source}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm">
                      <span className="px-2 py-1 bg-blue-900/30 text-blue-300 rounded text-xs">{item.type}</span>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-300">{item.tables}</td>
                    <td className="px-6 py-4 text-sm">
                      <span className={`px-2 py-1 rounded text-xs ${
                        item.status === 'connected' ? 'bg-green-900/30 text-green-300' : 'bg-red-900/30 text-red-300'
                      }`}>
                        {item.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-400">{item.updated_at}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          <div className="flex items-center justify-between px-6 py-3 border-t border-gray-700">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page === 1}
              className="px-3 py-1 text-sm text-gray-400 hover:text-white disabled:opacity-50"
            >
              ← Previous
            </button>
            <span className="text-sm text-gray-400">Page {page}</span>
            <button
              onClick={() => setPage(page + 1)}
              className="px-3 py-1 text-sm text-gray-400 hover:text-white"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
