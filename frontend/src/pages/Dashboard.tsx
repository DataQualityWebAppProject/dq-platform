import { useState, useEffect } from 'react'
import { Database, ShieldCheck, AlertTriangle, TrendingUp } from 'lucide-react'
import QualityLineChart from '../components/Charts/QualityLineChart'
import PassFailBarChart from '../components/Charts/PassFailBarChart'
import api from '../services/api'

interface DashboardStats {
  totalDatasets: number
  qualityScore: number
  anomaliesDetected: number
  rulesActive: number
}

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats>({
    totalDatasets: 12,
    qualityScore: 87,
    anomaliesDetected: 47,
    rulesActive: 34,
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadDashboard()
  }, [])

  const loadDashboard = async () => {
    try {
      const res = await api.get('/governance/dashboard')
      if (res.data) {
        setStats(res.data)
      }
    } catch {
      // Use default demo data if API isn't ready
    } finally {
      setLoading(false)
    }
  }

  const qualityTrend = [
    { date: 'Jan 1', score: 78 },
    { date: 'Jan 5', score: 82 },
    { date: 'Jan 10', score: 79 },
    { date: 'Jan 15', score: 85 },
    { date: 'Jan 20', score: 88 },
    { date: 'Jan 25', score: 84 },
    { date: 'Jan 30', score: 87 },
  ]

  const validationResults = [
    { name: 'customers', passed: 11, failed: 1 },
    { name: 'orders', passed: 6, failed: 2 },
    { name: 'products', passed: 5, failed: 0 },
    { name: 'users', passed: 8, failed: 3 },
    { name: 'transactions', passed: 9, failed: 1 },
  ]

  const summaryCards = [
    { label: 'Total Datasets', value: stats.totalDatasets, icon: Database, color: 'text-blue-400', bg: 'bg-blue-900/20', border: 'border-blue-800/50' },
    { label: 'Quality Score', value: `${stats.qualityScore}%`, icon: ShieldCheck, color: 'text-green-400', bg: 'bg-green-900/20', border: 'border-green-800/50' },
    { label: 'Anomalies', value: stats.anomaliesDetected, icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-900/20', border: 'border-amber-800/50' },
    { label: 'Active Rules', value: stats.rulesActive, icon: TrendingUp, color: 'text-purple-400', bg: 'bg-purple-900/20', border: 'border-purple-800/50' },
  ]

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-gray-400 text-sm mt-1">Overview of your data quality metrics</p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {summaryCards.map((card) => {
          const Icon = card.icon
          return (
            <div key={card.label} className={`${card.bg} rounded-xl border ${card.border} p-5`}>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-400">{card.label}</p>
                  <p className={`text-3xl font-bold mt-1 ${card.color}`}>
                    {loading ? '—' : card.value}
                  </p>
                </div>
                <Icon className={`h-8 w-8 ${card.color} opacity-60`} />
              </div>
            </div>
          )
        })}
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <QualityLineChart data={qualityTrend} title="Quality Score Trend" />
        <PassFailBarChart data={validationResults} title="Validation Results by Dataset" />
      </div>

      {/* Recent Activity */}
      <div className="mt-6 bg-gray-800 rounded-xl border border-gray-700 p-6">
        <h3 className="text-sm font-medium text-gray-300 mb-4">Recent Activity</h3>
        <div className="space-y-3">
          {[
            { action: 'Validation completed', detail: 'customers.csv — 94% quality score', time: '10 min ago', color: 'bg-green-500' },
            { action: 'Anomaly detected', detail: '8 outliers in order.amount field', time: '2 hours ago', color: 'bg-amber-500' },
            { action: 'Cleaning executed', detail: 'clean_customers.py — 1,024 rows processed', time: '5 hours ago', color: 'bg-blue-500' },
            { action: 'New rule created', detail: 'Email format validation rule', time: '1 day ago', color: 'bg-purple-500' },
          ].map((activity, idx) => (
            <div key={idx} className="flex items-center gap-3 p-3 bg-gray-900/50 rounded-lg">
              <div className={`w-2 h-2 rounded-full ${activity.color}`} />
              <div className="flex-1">
                <p className="text-sm text-white">{activity.action}</p>
                <p className="text-xs text-gray-400">{activity.detail}</p>
              </div>
              <span className="text-xs text-gray-500">{activity.time}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
