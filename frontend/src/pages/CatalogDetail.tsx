import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Database, Table2, Columns3 } from 'lucide-react'
import LoadingSpinner from '../components/LoadingSpinner'
import api from '../services/api'

interface TableInfo {
  name: string
  rowCount: number
  columns: number
  lastUpdated: string
}

interface CatalogSource {
  id: string
  name: string
  type: string
  connectionStatus: string
  tables: TableInfo[]
}

export default function CatalogDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [source, setSource] = useState<CatalogSource | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSource()
  }, [id])

  const loadSource = async () => {
    setLoading(true)
    try {
      const res = await api.get(`/governance/catalog/${id}`)
      setSource(res.data)
    } catch {
      // Demo data fallback
      setSource({
        id: id || '1',
        name: 'Production PostgreSQL',
        type: 'PostgreSQL',
        connectionStatus: 'connected',
        tables: [
          { name: 'customers', rowCount: 54230, columns: 12, lastUpdated: '2025-01-15' },
          { name: 'orders', rowCount: 128450, columns: 8, lastUpdated: '2025-01-15' },
          { name: 'products', rowCount: 3420, columns: 15, lastUpdated: '2025-01-14' },
          { name: 'transactions', rowCount: 892100, columns: 10, lastUpdated: '2025-01-15' },
          { name: 'users', rowCount: 12300, columns: 9, lastUpdated: '2025-01-13' },
        ],
      })
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="p-8">
        <LoadingSpinner message="Loading catalog details..." />
      </div>
    )
  }

  if (!source) return null

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <button
          onClick={() => navigate('/catalog')}
          className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <Database className="h-6 w-6 text-blue-400" />
            {source.name}
          </h1>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-sm text-gray-400">{source.type}</span>
            <span className={`px-2 py-0.5 rounded text-xs ${
              source.connectionStatus === 'connected' ? 'bg-green-900/30 text-green-300' : 'bg-red-900/30 text-red-300'
            }`}>
              {source.connectionStatus}
            </span>
          </div>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 text-gray-400 mb-1">
            <Table2 className="h-4 w-4" />
            <span className="text-xs">Tables</span>
          </div>
          <p className="text-2xl font-bold text-white">{source.tables.length}</p>
        </div>
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 text-gray-400 mb-1">
            <Columns3 className="h-4 w-4" />
            <span className="text-xs">Total Columns</span>
          </div>
          <p className="text-2xl font-bold text-white">
            {source.tables.reduce((acc, t) => acc + t.columns, 0)}
          </p>
        </div>
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 text-gray-400 mb-1">
            <Database className="h-4 w-4" />
            <span className="text-xs">Total Rows</span>
          </div>
          <p className="text-2xl font-bold text-white">
            {source.tables.reduce((acc, t) => acc + t.rowCount, 0).toLocaleString()}
          </p>
        </div>
      </div>

      {/* Tables List */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-700">
          <h2 className="text-sm font-medium text-gray-300">Tables</h2>
        </div>
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-700">
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Table Name</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Rows</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Columns</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Last Updated</th>
            </tr>
          </thead>
          <tbody>
            {source.tables.map((table) => (
              <tr key={table.name} className="border-b border-gray-700/50 hover:bg-gray-700/30">
                <td className="px-6 py-4 text-sm text-white font-medium font-mono">{table.name}</td>
                <td className="px-6 py-4 text-sm text-gray-300">{table.rowCount.toLocaleString()}</td>
                <td className="px-6 py-4 text-sm text-gray-300">{table.columns}</td>
                <td className="px-6 py-4 text-sm text-gray-400">{table.lastUpdated}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
