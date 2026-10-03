import { useState, useEffect } from 'react'
import { Play, FileCode, ChevronDown, CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import api from '../services/api'

interface CatalogOption {
  id: string
  name: string
}

interface TableOption {
  id: string
  name: string
}

export default function Cleaning() {
  const [catalogs, setCatalogs] = useState<CatalogOption[]>([])
  const [tables, setTables] = useState<TableOption[]>([])
  const [selectedCatalog, setSelectedCatalog] = useState('')
  const [selectedTable, setSelectedTable] = useState('')
  const [loadingCatalogs, setLoadingCatalogs] = useState(false)
  const [loadingTables, setLoadingTables] = useState(false)

  const [issues, setIssues] = useState('')
  const [generating, setGenerating] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [generatedScript, setGeneratedScript] = useState('')
  const [executionResult, setExecutionResult] = useState<{
    originalRows: number
    cleanedRows: number
    removedRows: number
  } | null>(null)
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
    setGeneratedScript('')
    setExecutionResult(null)
    setError('')
  }, [selectedCatalog])

  useEffect(() => {
    setGeneratedScript('')
    setExecutionResult(null)
    setError('')
  }, [selectedTable])

  const loadCatalogs = async () => {
    setLoadingCatalogs(true)
    try {
      const res = await api.get('/catalog', { params: { limit: 50 } })
      setCatalogs((res.data?.items || []).map((c: any) => ({ id: c.id, name: c.name })))
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
      setTables((res.data?.items || []).map((t: any) => ({ id: t.id || t.name, name: t.name || t.fileName })))
    } catch (err) {
      console.error('Failed to load tables:', err)
      setTables([])
    } finally {
      setLoadingTables(false)
    }
  }

  const handleGenerate = async () => {
    if (!selectedCatalog || !selectedTable) return
    setGenerating(true)
    setError('')
    setGeneratedScript('')
    setExecutionResult(null)

    try {
      const res = await api.post('/cleaning/generate', {
        catalogId: selectedCatalog,
        tableId: selectedTable,
        issues: issues || undefined,
      })
      setGeneratedScript(res.data?.script || '')
    } catch (err: any) {
      setError(err?.response?.data?.error || err?.message || 'Script generation failed')
    } finally {
      setGenerating(false)
    }
  }

  const handleExecute = async () => {
    if (!generatedScript || !selectedCatalog || !selectedTable) return
    setExecuting(true)
    setError('')
    setExecutionResult(null)

    try {
      const res = await api.post('/cleaning/execute', {
        catalogId: selectedCatalog,
        tableId: selectedTable,
        script: generatedScript,
      })
      setExecutionResult({
        originalRows: res.data?.originalRows || 0,
        cleanedRows: res.data?.cleanedRows || 0,
        removedRows: res.data?.removedRows || 0,
      })
    } catch (err: any) {
      setError(err?.response?.data?.error || err?.message || 'Cleaning execution failed')
    } finally {
      setExecuting(false)
    }
  }

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Data Cleaning</h1>
        <p className="text-gray-500 text-sm mt-1">Generate and execute AI-powered cleaning scripts</p>
      </div>

      {/* Target Selection */}
      <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-6 mb-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Select Target</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Catalog <span className="text-red-500">*</span></label>
            <div className="relative">
              <select value={selectedCatalog} onChange={(e) => setSelectedCatalog(e.target.value)}
                className="w-full px-3 py-2 bg-white/60 border border-white/80 rounded-xl text-sm appearance-none"
                disabled={loadingCatalogs}>
                <option value="">Select catalog...</option>
                {catalogs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Table <span className="text-red-500">*</span></label>
            <div className="relative">
              <select value={selectedTable} onChange={(e) => setSelectedTable(e.target.value)}
                className="w-full px-3 py-2 bg-white/60 border border-white/80 rounded-xl text-sm appearance-none disabled:bg-gray-100/60"
                disabled={!selectedCatalog || loadingTables}>
                <option value="">{loadingTables ? 'Loading...' : 'Select table...'}</option>
                {tables.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            </div>
          </div>
        </div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-gray-600 mb-1">Issues to fix (optional)</label>
          <input
            type="text"
            value={issues}
            onChange={(e) => setIssues(e.target.value)}
            placeholder="e.g., remove duplicates, fix null values in ABONO column, trim strings..."
            className="w-full px-3 py-2 bg-white/60 border border-white/80 rounded-xl text-sm placeholder-gray-400"
          />
        </div>

        <button
          onClick={handleGenerate}
          disabled={generating || !selectedCatalog || !selectedTable}
          className="px-5 py-2.5 btn-glass-primary disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl text-sm font-medium flex items-center gap-2"
        >
          {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileCode className="h-4 w-4" />}
          {generating ? 'Generating Script...' : 'Generate Cleaning Script'}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-6 flex items-center gap-2">
          <XCircle className="h-5 w-5 text-red-500" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Generated Script */}
      {generatedScript && (
        <div className="glass-card rounded-2xl shadow-lg shadow-black/5 overflow-hidden mb-6">
          <div className="flex items-center justify-between px-6 py-3 border-b border-white/40 bg-white/20">
            <span className="text-sm font-medium text-gray-700">Generated Cleaning Script</span>
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 bg-violet-100 text-violet-700 rounded text-xs font-medium">Python</span>
              <button
                onClick={handleExecute}
                disabled={executing}
                className="px-3 py-1.5 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white rounded-lg text-xs font-medium flex items-center gap-1.5"
              >
                {executing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                {executing ? 'Running...' : 'Execute'}
              </button>
            </div>
          </div>
          <pre className="p-6 text-xs text-green-400 bg-gray-900 overflow-x-auto font-mono leading-relaxed">
            <code>{generatedScript}</code>
          </pre>
        </div>
      )}

      {/* Execution Result */}
      {executionResult && (
        <div className="bg-green-50 border border-green-200 rounded-2xl p-6">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 className="h-5 w-5 text-green-600" />
            <h3 className="text-sm font-semibold text-green-800">Cleaning Complete</h3>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="text-center">
              <p className="text-2xl font-bold text-gray-900">{executionResult.originalRows}</p>
              <p className="text-xs text-gray-500">Original Rows</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-green-600">{executionResult.cleanedRows}</p>
              <p className="text-xs text-gray-500">Cleaned Rows</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-red-600">{executionResult.removedRows}</p>
              <p className="text-xs text-gray-500">Removed Rows</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
