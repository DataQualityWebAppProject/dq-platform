import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Database, Table2, Columns3, FileText, ChevronDown, ChevronRight } from 'lucide-react'
import LoadingSpinner from '../components/LoadingSpinner'
import api from '../services/api'

interface ColumnDef {
  name: string
  type: string
}

interface TableInfo {
  id: string
  name: string
  fileName: string
  rowCount: number
  columns: ColumnDef[]
  separator?: string
  createdAt?: string
}

interface CatalogData {
  id: string
  name: string
  description: string
  owner: string
  tables: TableInfo[]
}

export default function CatalogDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [catalog, setCatalog] = useState<CatalogData | null>(null)
  const [loading, setLoading] = useState(true)
  const [expandedTable, setExpandedTable] = useState<string | null>(null)

  useEffect(() => {
    loadCatalog()
  }, [id])

  const loadCatalog = async () => {
    setLoading(true)
    try {
      // Load catalog info
      const catalogRes = await api.get(`/catalog/${id}`)
      const catalogData = catalogRes.data

      // Load tables for this catalog
      let tables: TableInfo[] = []
      try {
        const tablesRes = await api.get(`/catalog/${id}/tables`)
        const rawTables = tablesRes.data?.items || tablesRes.data || []
        tables = rawTables.map((t: any) => ({
          id: t.id || t.tableId || '',
          name: t.name || t.fileName || 'Unknown',
          fileName: t.fileName || '',
          rowCount: t.rowCount || 0,
          columns: (t.columns || []).map((c: any) => ({
            name: c.name || '',
            type: c.type || c.inferredType || 'string',
          })),
          separator: t.separator || ',',
          createdAt: t.createdAt || '',
        }))
      } catch {
        // Tables endpoint may not exist yet — use empty
        tables = []
      }

      setCatalog({
        id: catalogData.id || id || '',
        name: catalogData.name || 'Catalog',
        description: catalogData.description || '',
        owner: catalogData.owner || '',
        tables,
      })
    } catch {
      // Fallback for when API is unavailable
      setCatalog({
        id: id || '',
        name: 'Catalog',
        description: '',
        owner: '',
        tables: [],
      })
    } finally {
      setLoading(false)
    }
  }

  const toggleTable = (tableId: string) => {
    setExpandedTable(prev => prev === tableId ? null : tableId)
  }

  if (loading) {
    return (
      <div className="p-8">
        <LoadingSpinner message="Loading catalog details..." />
      </div>
    )
  }

  if (!catalog) return null

  const totalColumns = catalog.tables.reduce((acc, t) => acc + t.columns.length, 0)
  const totalRows = catalog.tables.reduce((acc, t) => acc + t.rowCount, 0)

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <button
          onClick={() => navigate('/catalog')}
          className="p-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
            <Database className="h-6 w-6 text-violet-500" />
            {catalog.name}
          </h1>
          {catalog.description && (
            <p className="text-sm text-gray-500 mt-1">{catalog.description}</p>
          )}
          {catalog.owner && (
            <span className="text-xs text-gray-400">Owner: {catalog.owner}</span>
          )}
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-4">
          <div className="flex items-center gap-2 text-gray-500 mb-1">
            <Table2 className="h-4 w-4" />
            <span className="text-xs">Tables</span>
          </div>
          <p className="text-2xl font-bold text-gray-900">{catalog.tables.length}</p>
        </div>
        <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-4">
          <div className="flex items-center gap-2 text-gray-500 mb-1">
            <Columns3 className="h-4 w-4" />
            <span className="text-xs">Total Columns</span>
          </div>
          <p className="text-2xl font-bold text-gray-900">{totalColumns}</p>
        </div>
        <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-4">
          <div className="flex items-center gap-2 text-gray-500 mb-1">
            <FileText className="h-4 w-4" />
            <span className="text-xs">Total Rows</span>
          </div>
          <p className="text-2xl font-bold text-gray-900">{totalRows.toLocaleString()}</p>
        </div>
      </div>

      {/* Tables List */}
      <div className="glass-card rounded-2xl shadow-lg shadow-black/5 overflow-hidden">
        <div className="px-6 py-4 border-b border-white/40 bg-white/20">
          <h2 className="text-sm font-semibold text-gray-700">Tables (Uploaded CSVs)</h2>
        </div>

        {catalog.tables.length === 0 ? (
          <div className="p-8 text-center">
            <Table2 className="h-10 w-10 text-gray-300 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No tables uploaded yet.</p>
            <a
              href="/upload"
              className="mt-3 inline-block text-sm text-violet-600 hover:text-violet-700 font-medium"
            >
              Upload a dataset →
            </a>
          </div>
        ) : (
          <div>
            {catalog.tables.map((table) => (
              <div key={table.id} className="border-b border-white/30 last:border-b-0">
                {/* Table row */}
                <button
                  onClick={() => toggleTable(table.id)}
                  className="w-full flex items-center justify-between px-6 py-4 hover:bg-white/30 transition-colors text-left"
                >
                  <div className="flex items-center gap-3">
                    {expandedTable === table.id ? (
                      <ChevronDown className="h-4 w-4 text-gray-400" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-gray-400" />
                    )}
                    <div>
                      <p className="text-sm font-medium text-gray-900">{table.fileName || table.name}</p>
                      {table.createdAt && (
                        <p className="text-xs text-gray-400">{new Date(table.createdAt).toLocaleDateString()}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-6">
                    <div className="text-right">
                      <p className="text-xs text-gray-400">Columns</p>
                      <p className="text-sm font-medium text-gray-700">{table.columns.length}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-gray-400">Rows</p>
                      <p className="text-sm font-medium text-gray-700">{table.rowCount.toLocaleString()}</p>
                    </div>
                  </div>
                </button>

                {/* Expanded columns */}
                {expandedTable === table.id && table.columns.length > 0 && (
                  <div className="bg-white/20 px-6 py-3 border-t border-white/30">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-gray-500">
                          <th className="text-left py-1 font-medium">Column Name</th>
                          <th className="text-left py-1 font-medium">Data Type</th>
                        </tr>
                      </thead>
                      <tbody>
                        {table.columns.map((col, idx) => (
                          <tr key={idx} className="border-t border-white/20">
                            <td className="py-1.5 text-gray-800 font-mono">{col.name}</td>
                            <td className="py-1.5">
                              <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                                col.type === 'integer' ? 'bg-violet-100 text-violet-700' :
                                col.type === 'float' ? 'bg-fuchsia-100 text-fuchsia-700' :
                                col.type === 'date' ? 'bg-orange-100 text-orange-700' :
                                col.type === 'boolean' ? 'bg-green-100 text-green-700' :
                                'bg-gray-100 text-gray-700'
                              }`}>
                                {col.type}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
