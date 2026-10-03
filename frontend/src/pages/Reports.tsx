import { useState, useEffect } from 'react'
import { marked } from 'marked'
import api from '../services/api'

interface CatalogOption {
  id: string
  name: string
}

export default function Reports() {
  const [catalogs, setCatalogs] = useState<CatalogOption[]>([])
  const [selectedCatalog, setSelectedCatalog] = useState('')
  const [generating, setGenerating] = useState(false)
  const [reportHtml, setReportHtml] = useState('')
  const [reportMeta, setReportMeta] = useState<{ catalogName: string; generatedAt: string } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/catalog', { params: { limit: 50 } }).then(res => {
      setCatalogs((res.data?.items || []).map((c: any) => ({ id: c.id, name: c.name })))
    }).catch(() => {})
  }, [])

  const handleGenerate = async () => {
    if (!selectedCatalog) return
    setGenerating(true)
    setError('')
    setReportHtml('')
    setReportMeta(null)

    try {
      const res = await api.post('/reports/generate', { catalogId: selectedCatalog })
      const md = res.data?.report || ''
      const html = marked(md) as string
      setReportHtml(html)
      setReportMeta({
        catalogName: res.data?.catalogName || '',
        generatedAt: res.data?.generatedAt || '',
      })
    } catch (err: any) {
      setError(err?.response?.data?.error || err?.message || 'Error generando reporte')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-gray-800 mb-1">Reportes</h1>
      <p className="text-sm text-gray-500 mb-6">Genera reportes ejecutivos de calidad con IA</p>

      {/* Controls */}
      <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-4 mb-4">
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <label className="block text-xs text-gray-600 mb-1">Catálogo</label>
            <select value={selectedCatalog} onChange={(e) => setSelectedCatalog(e.target.value)}
              className="w-full px-3 py-2 bg-white/60 border border-white/80 rounded-xl text-sm">
              <option value="">Seleccionar catálogo...</option>
              {catalogs.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <button onClick={handleGenerate} disabled={generating || !selectedCatalog}
            className="px-4 py-2 btn-glass-primary text-white text-sm rounded-xl disabled:opacity-40">
            {generating ? 'Generando...' : 'Generar Reporte'}
          </button>
        </div>
      </div>

      {error && <div className="bg-red-50 border border-red-300 text-red-800 text-sm p-3 rounded-xl mb-4">{error}</div>}

      {/* Report rendered as HTML */}
      {reportHtml && reportMeta && (
        <div className="glass-card rounded-2xl shadow-lg shadow-black/5 overflow-hidden">
          <div className="px-5 py-3 border-b border-white/40 bg-white/20 flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-800">{reportMeta.catalogName}</p>
              <p className="text-xs text-gray-500">{reportMeta.generatedAt}</p>
            </div>
            <span className="text-xs bg-green-100 text-green-800 px-2 py-0.5 rounded">Generado</span>
          </div>
          <div
            className="p-6 prose prose-sm max-w-none
              prose-headings:text-gray-900 prose-headings:font-semibold
              prose-h1:text-lg prose-h1:border-b prose-h1:border-gray-200 prose-h1:pb-2
              prose-h2:text-base prose-h2:mt-6 prose-h2:mb-2
              prose-h3:text-sm
              prose-p:text-gray-700 prose-p:leading-relaxed
              prose-li:text-gray-700
              prose-strong:text-gray-900
              prose-table:border-collapse prose-table:w-full
              prose-th:bg-gray-100 prose-th:border prose-th:border-gray-300 prose-th:px-3 prose-th:py-2 prose-th:text-left prose-th:text-xs prose-th:font-medium prose-th:text-gray-600
              prose-td:border prose-td:border-gray-200 prose-td:px-3 prose-td:py-2 prose-td:text-sm
              prose-code:bg-gray-100 prose-code:px-1 prose-code:rounded prose-code:text-sm"
            dangerouslySetInnerHTML={{ __html: reportHtml }}
          />
        </div>
      )}

      {!reportHtml && !generating && (
        <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-10 text-center text-gray-400 text-sm">
          Selecciona un catálogo y genera un reporte
        </div>
      )}
    </div>
  )
}
