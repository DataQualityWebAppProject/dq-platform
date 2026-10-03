import { useState, useEffect } from 'react'
import { Play, Clock, ChevronDown, CheckCircle2, XCircle, BarChart3 } from 'lucide-react'
import api from '../services/api'

interface CatalogOption {
  id: string
  name: string
}

interface TableOption {
  id: string
  name: string
}

interface RuleResult {
  ruleId: string
  ruleName: string
  columnId: string
  totalRows: number
  passedRows: number
  failedRows: number
  score: number
}

interface ValidationResult {
  success: boolean
  totalRows: number
  totalRules: number
  overallScore: number
  results: RuleResult[]
}

export default function Validation() {
  const [catalogs, setCatalogs] = useState<CatalogOption[]>([])
  const [tables, setTables] = useState<TableOption[]>([])
  const [selectedCatalog, setSelectedCatalog] = useState('')
  const [selectedTable, setSelectedTable] = useState('')
  const [loadingCatalogs, setLoadingCatalogs] = useState(false)
  const [loadingTables, setLoadingTables] = useState(false)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<ValidationResult | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    loadCatalogs()
  }, [])

  useEffect(() => {
    if (selectedCatalog) {
      loadTables(selectedCatalog)
    } else {
      setTables([])
      setSelectedTable('')
    }
    setResult(null)
    setError('')
  }, [selectedCatalog])

  useEffect(() => {
    setResult(null)
    setError('')
  }, [selectedTable])

  const loadCatalogs = async () => {
    setLoadingCatalogs(true)
    try {
      const res = await api.get('/catalog', { params: { limit: 50 } })
      const items = res.data?.items || []
      setCatalogs(items.map((c: any) => ({ id: c.id, name: c.name })))
    } catch (err) {
      console.error('Failed to load catalogs:', err)
    } finally {
      setLoadingCatalogs(false)
    }
  }

  const loadTables = async (catalogId: string) => {
    setLoadingTables(true)
    setSelectedTable('')
    try {
      const res = await api.get(`/catalog/${catalogId}/tables`)
      const items = res.data?.items || []
      setTables(items.map((t: any) => ({
        id: t.id || t.name,
        name: t.name || t.fileName || '',
      })))
    } catch (err) {
      console.error('Failed to load tables:', err)
      setTables([])
    } finally {
      setLoadingTables(false)
    }
  }

  const handleRunValidation = async () => {
    if (!selectedCatalog || !selectedTable) return
    setRunning(true)
    setError('')
    setResult(null)

    try {
      const res = await api.post('/validations', {
        datasetId: selectedTable,
        catalogId: selectedCatalog,
        tableId: selectedTable,
      })
      setResult(res.data)
    } catch (err: any) {
      setError(err?.response?.data?.error?.message || err?.response?.data?.error || err?.response?.data?.detail || err?.message || 'Validation failed')
    } finally {
      setRunning(false)
    }
  }

  const getScoreColor = (score: number) => {
    if (score >= 90) return 'text-green-600'
    if (score >= 70) return 'text-yellow-600'
    return 'text-red-600'
  }

  const getScoreBg = (score: number) => {
    if (score >= 90) return 'bg-green-50 border-green-200'
    if (score >= 70) return 'bg-yellow-50 border-yellow-200'
    return 'bg-red-50 border-red-200'
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Validation</h1>
          <p className="text-gray-500 text-sm mt-1">Run data quality rules against your tables</p>
        </div>
      </div>

      {/* Catalog + Table Selectors */}
      <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-6 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <BarChart3 className="h-4 w-4 text-violet-500" />
          <h2 className="text-sm font-semibold text-gray-700">Select Target</h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          {/* Catalog Selector */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Catalog <span className="text-red-500">*</span>
            </label>
            <div className="relative">
              <select
                value={selectedCatalog}
                onChange={(e) => setSelectedCatalog(e.target.value)}
                className="w-full px-3 py-2 bg-white/60 border border-white/80 rounded-xl text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-violet-500 appearance-none"
                disabled={loadingCatalogs}
              >
                <option value="">Select catalog...</option>
                {catalogs.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            </div>
          </div>

          {/* Table Selector */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Table <span className="text-red-500">*</span>
            </label>
            <div className="relative">
              <select
                value={selectedTable}
                onChange={(e) => setSelectedTable(e.target.value)}
                className="w-full px-3 py-2 bg-white/60 border border-white/80 rounded-xl text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-violet-500 appearance-none disabled:bg-gray-100/60 disabled:text-gray-400"
                disabled={!selectedCatalog || loadingTables}
              >
                <option value="">{loadingTables ? 'Loading...' : 'Select table...'}</option>
                {tables.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            </div>
          </div>
        </div>

        <button
          onClick={handleRunValidation}
          disabled={running || !selectedCatalog || !selectedTable}
          className="px-6 py-2.5 bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl text-sm font-medium transition-colors flex items-center gap-2 shadow-lg shadow-green-600/20"
        >
          <Play className="h-4 w-4" />
          {running ? 'Running Validation...' : 'Run Validation'}
        </button>
      </div>

      {/* Error Display */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
          <div className="flex items-center gap-2">
            <XCircle className="h-5 w-5 text-red-500" />
            <p className="text-sm text-red-700">{error}</p>
          </div>
        </div>
      )}

      {/* Results */}
      {result && (
        <>
          {/* Overall Score */}
          <div className={`rounded-2xl border p-6 mb-6 ${getScoreBg(result.overallScore)}`}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600 mb-1">Overall Quality Score</p>
                <p className={`text-5xl font-bold ${getScoreColor(result.overallScore)}`}>
                  {result.overallScore}%
                </p>
              </div>
              <div className="text-right text-sm text-gray-600 space-y-1">
                <p><span className="font-medium">{result.totalRows.toLocaleString()}</span> rows analyzed</p>
                <p><span className="font-medium">{result.totalRules}</span> rules evaluated</p>
              </div>
            </div>
          </div>

          {/* Per-Rule Results */}
          {result.results.length > 0 ? (
            <div className="glass-card rounded-2xl shadow-lg shadow-black/5 overflow-hidden">
              <div className="flex items-center gap-2 px-6 py-4 border-b border-white/40 bg-white/20">
                <Clock className="h-4 w-4 text-gray-500" />
                <h2 className="text-sm font-semibold text-gray-700">Per-Rule Results</h2>
              </div>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-200">
                    <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Rule</th>
                    <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Column</th>
                    <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                    <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Score</th>
                    <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Passed / Failed</th>
                  </tr>
                </thead>
                <tbody>
                  {result.results.map((r) => (
                    <tr key={r.ruleId} className="border-b border-white/30 hover:bg-white/30 transition-colors">
                      <td className="px-6 py-4 text-sm text-gray-900 font-medium max-w-xs truncate">{r.ruleName}</td>
                      <td className="px-6 py-4 text-sm text-gray-500 font-mono">{r.columnId}</td>
                      <td className="px-6 py-4 text-sm">
                        {r.score >= 90 ? (
                          <span className="flex items-center gap-1 text-green-600">
                            <CheckCircle2 className="h-4 w-4" /> Pass
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-red-600">
                            <XCircle className="h-4 w-4" /> Fail
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4 text-sm">
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-2 bg-gray-200 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${r.score >= 90 ? 'bg-green-500' : r.score >= 70 ? 'bg-yellow-500' : 'bg-red-500'}`}
                              style={{ width: `${r.score}%` }}
                            />
                          </div>
                          <span className={`font-medium ${getScoreColor(r.score)}`}>{r.score}%</span>
                        </div>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500">
                        <span className="text-green-600 font-medium">{r.passedRows.toLocaleString()}</span>
                        {' / '}
                        <span className="text-red-600 font-medium">{r.failedRows.toLocaleString()}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-8 text-center">
              <p className="text-gray-500">No rules found for this catalog. Create rules first in the Rules page.</p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
