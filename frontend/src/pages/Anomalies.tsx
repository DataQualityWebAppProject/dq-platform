import { useState, useEffect } from 'react'
import { ChevronDown, Loader2 } from 'lucide-react'
import api from '../services/api'

interface CatalogOption { id: string; name: string }
interface TableOption { id: string; name: string }
interface AnomalyResult {
  recordIndex: number
  reconstructionError: number
  severity: string
  affectedColumns: string[]
}

export default function Anomalies() {
  const [catalogs, setCatalogs] = useState<CatalogOption[]>([])
  const [tables, setTables] = useState<TableOption[]>([])
  const [selectedCatalog, setSelectedCatalog] = useState('')
  const [selectedTable, setSelectedTable] = useState('')
  const [loadingTables, setLoadingTables] = useState(false)
  const [training, setTraining] = useState(false)
  const [error, setError] = useState('')

  const [result, setResult] = useState<{
    totalRecords: number
    numericFeatures: number
    featureNames: string[]
    threshold: number
    totalAnomalies: number
    anomalyRate: number
    anomalies: AnomalyResult[]
    trainedAt: string
  } | null>(null)

  useEffect(() => {
    api.get('/catalog', { params: { limit: 50 } }).then(res => {
      setCatalogs((res.data?.items || []).map((c: any) => ({ id: c.id, name: c.name })))
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (selectedCatalog) {
      setLoadingTables(true)
      setSelectedTable('')
      setResult(null)
      api.get(`/catalog/${selectedCatalog}/tables`).then(res => {
        setTables((res.data?.items || []).map((t: any) => ({ id: t.id || t.name, name: t.name })))
      }).catch(() => setTables([])).finally(() => setLoadingTables(false))
    } else {
      setTables([])
      setSelectedTable('')
    }
  }, [selectedCatalog])

  const handleTrain = async () => {
    if (!selectedCatalog || !selectedTable) return
    setTraining(true)
    setError('')
    setResult(null)

    try {
      const res = await api.post('/anomalies/train', {
        catalogId: selectedCatalog,
        tableId: selectedTable,
      })
      setResult(res.data)
    } catch (err: any) {
      setError(err?.response?.data?.error || err?.message || 'Training failed')
    } finally {
      setTraining(false)
    }
  }

  const severityColor = (s: string) => {
    if (s === 'critical') return 'bg-red-600 text-white'
    if (s === 'high') return 'bg-red-100 text-red-800'
    if (s === 'medium') return 'bg-yellow-100 text-yellow-800'
    return 'bg-gray-100 text-gray-700'
  }

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-gray-800 mb-1">Detección de Anomalías</h1>
      <p className="text-sm text-gray-500 mb-6">Autoencoder que aprende patrones normales y detecta outliers</p>

      {/* Controls */}
      <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-4 mb-4">
        <div className="grid grid-cols-3 gap-3 items-end">
          <div>
            <label className="block text-xs text-gray-600 mb-1">Catálogo</label>
            <div className="relative">
              <select value={selectedCatalog} onChange={(e) => setSelectedCatalog(e.target.value)}
                className="w-full px-3 py-2 bg-white/60 border border-white/80 rounded-xl text-sm appearance-none">
                <option value="">Seleccionar...</option>
                {catalogs.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            </div>
          </div>
          <div>
            <label className="block text-xs text-gray-600 mb-1">Tabla</label>
            <div className="relative">
              <select value={selectedTable} onChange={(e) => setSelectedTable(e.target.value)}
                className="w-full px-3 py-2 bg-white/60 border border-white/80 rounded-xl text-sm appearance-none disabled:bg-gray-100/60"
                disabled={!selectedCatalog || loadingTables}>
                <option value="">{loadingTables ? 'Cargando...' : 'Seleccionar...'}</option>
                {tables.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
              <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            </div>
          </div>
          <button onClick={handleTrain} disabled={training || !selectedCatalog || !selectedTable}
            className="px-4 py-2 btn-glass-primary text-white text-sm rounded-xl disabled:opacity-40 flex items-center gap-2 justify-center">
            {training && <Loader2 className="h-4 w-4 animate-spin" />}
            {training ? 'Entrenando...' : 'Entrenar y Detectar'}
          </button>
        </div>
        <p className="text-[11px] text-gray-400 mt-2">El autoencoder se entrena con las columnas numéricas y detecta registros con patrones inusuales</p>
      </div>

      {error && <div className="bg-red-50 border border-red-300 text-red-800 text-sm p-3 rounded mb-4">{error}</div>}

      {/* Results */}
      {result && (
        <>
          {/* Stats */}
          <div className="grid grid-cols-5 gap-3 mb-4">
            <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-3">
              <p className="text-[10px] text-gray-500 uppercase">Registros</p>
              <p className="text-lg font-bold text-gray-900">{result.totalRecords}</p>
            </div>
            <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-3">
              <p className="text-[10px] text-gray-500 uppercase">Features</p>
              <p className="text-lg font-bold text-gray-900">{result.numericFeatures}</p>
            </div>
            <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-3">
              <p className="text-[10px] text-gray-500 uppercase">Threshold</p>
              <p className="text-lg font-bold text-gray-900">{result.threshold.toFixed(4)}</p>
            </div>
            <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-3">
              <p className="text-[10px] text-gray-500 uppercase">Anomalías</p>
              <p className="text-lg font-bold text-red-700">{result.totalAnomalies}</p>
            </div>
            <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-3">
              <p className="text-[10px] text-gray-500 uppercase">Tasa</p>
              <p className="text-lg font-bold text-gray-900">{result.anomalyRate}%</p>
            </div>
          </div>

          {/* Anomaly Table */}
          {result.anomalies.length > 0 ? (
            <div className="glass-card rounded-2xl shadow-lg shadow-black/5 overflow-hidden">
              <div className="px-4 py-3 border-b border-white/40 bg-white/20">
                <p className="text-xs font-medium text-gray-700">Registros anómalos detectados ({result.totalAnomalies})</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 text-xs text-gray-500">
                      <th className="text-left px-4 py-2">Fila</th>
                      <th className="text-left px-4 py-2">Error</th>
                      <th className="text-left px-4 py-2">Severidad</th>
                      <th className="text-left px-4 py-2">Columnas afectadas</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.anomalies.map((a, i) => (
                      <tr key={i} className="border-b border-white/30 hover:bg-white/30">
                        <td className="px-4 py-2 font-mono text-xs">{a.recordIndex}</td>
                        <td className="px-4 py-2 font-mono text-xs">{a.reconstructionError.toFixed(4)}</td>
                        <td className="px-4 py-2">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-medium uppercase ${severityColor(a.severity)}`}>
                            {a.severity}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-xs text-gray-600">{a.affectedColumns.join(', ')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="bg-green-50 border border-green-200 rounded-md p-4 text-center">
              <p className="text-sm text-green-800">No se detectaron anomalías en los datos</p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
