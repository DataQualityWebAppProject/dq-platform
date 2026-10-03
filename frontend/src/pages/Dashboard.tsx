import { useState, useEffect } from 'react'
import QualityLineChart from '../components/Charts/QualityLineChart'
import PassFailBarChart from '../components/Charts/PassFailBarChart'
import api from '../services/api'

export default function Dashboard() {
  const [totalDatasets, setTotalDatasets] = useState(0)
  const [qualityScore, setQualityScore] = useState(0)
  const [rulesActive, setRulesActive] = useState(0)
  const [loading, setLoading] = useState(true)
  const [validationResults, setValidationResults] = useState<{ name: string; passed: number; failed: number }[]>([])
  const [qualityTrend, setQualityTrend] = useState<{ date: string; score: number }[]>([])

  useEffect(() => {
    loadDashboard()
  }, [])

  const loadDashboard = async () => {
    try {
      const [catalogRes, rulesRes] = await Promise.allSettled([
        api.get('/catalog', { params: { limit: 50 } }),
        api.get('/rules', { params: { limit: 50 } }),
      ])

      const catalogs = catalogRes.status === 'fulfilled' ? (catalogRes.value.data?.items || []) : []
      const rules = rulesRes.status === 'fulfilled' ? (rulesRes.value.data?.items || []) : []

      setTotalDatasets(catalogs.length)
      setRulesActive(rules.length)

      // Run validation on first catalog with rules
      const catalogsWithRules = new Set(rules.map((r: any) => r.catalogId))
      for (const catalog of catalogs) {
        if (!catalogsWithRules.has(catalog.id)) continue
        try {
          const tablesRes = await api.get(`/catalog/${catalog.id}/tables`)
          const tables = tablesRes.data?.items || []
          if (tables.length === 0) continue

          const valRes = await api.post('/validations', {
            catalogId: catalog.id,
            tableId: tables[0].id,
          })
          if (valRes.data?.success) {
            setQualityScore(valRes.data.overallScore || 0)
            const results = valRes.data.results || []
            setValidationResults([{
              name: tables[0].name || catalog.name,
              passed: results.filter((r: any) => r.score >= 90).length,
              failed: results.filter((r: any) => r.score < 90).length,
            }])
            const today = new Date()
            setQualityTrend([
              { date: fmt(today, -6), score: 0 },
              { date: fmt(today, -5), score: 0 },
              { date: fmt(today, -4), score: 0 },
              { date: fmt(today, -3), score: 0 },
              { date: fmt(today, -2), score: 0 },
              { date: fmt(today, -1), score: 0 },
              { date: fmt(today, 0), score: valRes.data.overallScore || 0 },
            ])
          }
          break
        } catch { /* skip */ }
      }
    } catch { /* leave zeros */ }
    finally { setLoading(false) }
  }

  const fmt = (base: Date, offset: number) => {
    const d = new Date(base); d.setDate(d.getDate() + offset)
    return d.toLocaleDateString('es', { day: '2-digit', month: 'short' })
  }

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold text-gray-900 tracking-tight mb-1">Dashboard</h1>
      <p className="text-sm text-gray-500 mb-6">Resumen de calidad de datos</p>

      {/* KPI Cards - deep amethyst glass */}
      <div className="grid grid-cols-4 gap-6 mb-8">
        <div className="glass-card rounded-2xl p-6 shadow-lg shadow-black/5 hover:shadow-xl hover:shadow-black/10 transition-all">
          <p className="text-xs text-gray-500 uppercase tracking-widest font-semibold">Catálogos</p>
          <p className="text-3xl font-bold text-gray-900 mt-2">{loading ? '...' : totalDatasets}</p>
        </div>
        <div className="glass-card rounded-2xl p-6 shadow-lg shadow-black/5 hover:shadow-xl hover:shadow-black/10 transition-all">
          <p className="text-xs text-gray-500 uppercase tracking-widest font-semibold">Quality Score</p>
          <p className={`text-3xl font-bold mt-2 ${qualityScore >= 90 ? 'text-green-700' : qualityScore >= 70 ? 'text-yellow-700' : qualityScore > 0 ? 'text-red-700' : 'text-gray-400'}`}>
            {loading ? '...' : qualityScore > 0 ? `${qualityScore}%` : 'N/A'}
          </p>
        </div>
        <div className="glass-card rounded-2xl p-6 shadow-lg shadow-black/5 hover:shadow-xl hover:shadow-black/10 transition-all">
          <p className="text-xs text-gray-500 uppercase tracking-widest font-semibold">Reglas Activas</p>
          <p className="text-3xl font-bold text-gray-900 mt-2">{loading ? '...' : rulesActive}</p>
        </div>
        <div className="glass-card rounded-2xl p-6 shadow-lg shadow-black/5 hover:shadow-xl hover:shadow-black/10 transition-all">
          <p className="text-xs text-gray-500 uppercase tracking-widest font-semibold">Anomalías</p>
          <p className="text-3xl font-bold text-gray-400 mt-2">—</p>
          <p className="text-[10px] text-gray-400 mt-1">Pendiente GPU</p>
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-2 gap-6 mb-8">
        <div className="glass-card rounded-2xl p-6 shadow-lg shadow-black/5">
          <QualityLineChart data={qualityTrend.length > 0 ? qualityTrend : [{ date: 'Hoy', score: qualityScore }]} title="Tendencia de Calidad" />
        </div>
        <div className="glass-card rounded-2xl p-6 shadow-lg shadow-black/5">
          <PassFailBarChart data={validationResults} title="Resultados por Dataset" />
        </div>
      </div>

      {/* Quick actions */}
      <div className="glass-card rounded-2xl p-6 shadow-lg shadow-black/5">
        <p className="text-xs text-gray-400 uppercase tracking-widest font-bold mb-4">Acciones rápidas</p>
        <div className="flex flex-wrap gap-4">
          <a href="/upload" className="px-4 py-2 rounded-xl bg-white/50 border border-white/80 text-sm text-violet-700 font-semibold hover:bg-white hover:shadow-md transition-all">Subir dataset</a>
          <a href="/rules" className="px-4 py-2 rounded-xl bg-white/50 border border-white/80 text-sm text-violet-700 font-semibold hover:bg-white hover:shadow-md transition-all">Crear regla</a>
          <a href="/validation" className="px-4 py-2 rounded-xl bg-white/50 border border-white/80 text-sm text-violet-700 font-semibold hover:bg-white hover:shadow-md transition-all">Ejecutar validación</a>
          <a href="/cleaning" className="px-4 py-2 rounded-xl bg-white/50 border border-white/80 text-sm text-violet-700 font-semibold hover:bg-white hover:shadow-md transition-all">Limpieza</a>
          <a href="/reports" className="px-4 py-2 rounded-xl bg-white/50 border border-white/80 text-sm text-violet-700 font-semibold hover:bg-white hover:shadow-md transition-all">Generar reporte</a>
        </div>
      </div>
    </div>
  )
}
