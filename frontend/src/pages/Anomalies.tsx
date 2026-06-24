import { useState } from 'react'
import { AlertTriangle, Brain, Zap } from 'lucide-react'
import AnomalyRadarChart from '../components/Charts/AnomalyRadarChart'

export default function Anomalies() {
  const [trainingStatus] = useState<'idle' | 'training' | 'ready'>('ready')

  const stats = [
    { label: 'Total Anomalies', value: '47', color: 'text-red-400', bg: 'bg-red-900/20', border: 'border-red-800/50' },
    { label: 'Critical', value: '8', color: 'text-orange-400', bg: 'bg-orange-900/20', border: 'border-orange-800/50' },
    { label: 'Resolved', value: '32', color: 'text-green-400', bg: 'bg-green-900/20', border: 'border-green-800/50' },
    { label: 'Datasets Affected', value: '5', color: 'text-blue-400', bg: 'bg-blue-900/20', border: 'border-blue-800/50' },
  ]

  const radarData = [
    { field: 'email', count: 12, fullMark: 20 },
    { field: 'amount', count: 5, fullMark: 20 },
    { field: 'price', count: 3, fullMark: 20 },
    { field: 'age', count: 8, fullMark: 20 },
    { field: 'date', count: 6, fullMark: 20 },
    { field: 'name', count: 2, fullMark: 20 },
    { field: 'phone', count: 7, fullMark: 20 },
    { field: 'address', count: 4, fullMark: 20 },
  ]

  const anomalies = [
    { id: '1', field: 'customer.email', type: 'Format Violation', severity: 'HIGH', count: 12, detected: '2025-01-15', score: 0.95 },
    { id: '2', field: 'order.amount', type: 'Outlier', severity: 'MEDIUM', count: 5, detected: '2025-01-15', score: 0.78 },
    { id: '3', field: 'product.price', type: 'Null Value', severity: 'LOW', count: 3, detected: '2025-01-14', score: 0.45 },
    { id: '4', field: 'user.age', type: 'Range Violation', severity: 'HIGH', count: 8, detected: '2025-01-14', score: 0.91 },
    { id: '5', field: 'order.date', type: 'Pattern Shift', severity: 'MEDIUM', count: 6, detected: '2025-01-14', score: 0.72 },
    { id: '6', field: 'user.phone', type: 'Format Violation', severity: 'MEDIUM', count: 7, detected: '2025-01-13', score: 0.68 },
  ]

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Anomaly Detection</h1>
          <p className="text-gray-400 text-sm mt-1">ML-powered anomaly detection and scoring</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-lg">
            <Brain className="h-4 w-4 text-purple-400" />
            <span className="text-xs text-gray-300">
              Model: {trainingStatus === 'ready' ? 'Ready' : trainingStatus === 'training' ? 'Training...' : 'Not trained'}
            </span>
          </div>
          <button className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-2">
            <Zap className="h-4 w-4" />
            Run Scoring
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {stats.map((stat) => (
          <div key={stat.label} className={`${stat.bg} rounded-xl border ${stat.border} p-5`}>
            <p className="text-sm text-gray-400">{stat.label}</p>
            <p className={`text-3xl font-bold mt-1 ${stat.color}`}>{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Radar Chart + Training Config */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <AnomalyRadarChart data={radarData} title="Anomalies per Column" />

        {/* Training Configuration */}
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-6">
          <h3 className="text-sm font-medium text-gray-300 mb-4 flex items-center gap-2">
            <Brain className="h-4 w-4 text-purple-400" />
            Training Configuration
          </h3>
          <div className="space-y-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Algorithm</label>
              <select className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-purple-500">
                <option>Isolation Forest</option>
                <option>Autoencoder</option>
                <option>Local Outlier Factor</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Contamination Threshold</label>
              <input
                type="number"
                defaultValue={0.05}
                step={0.01}
                min={0.01}
                max={0.5}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Training Dataset</label>
              <select className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-purple-500">
                <option>customers.csv</option>
                <option>orders.csv</option>
                <option>All datasets</option>
              </select>
            </div>
            <button className="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg text-sm font-medium transition-colors">
              Train Model
            </button>
          </div>
        </div>
      </div>

      {/* Anomaly List */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        <div className="flex items-center gap-2 px-6 py-4 border-b border-gray-700">
          <AlertTriangle className="h-4 w-4 text-amber-400" />
          <h2 className="text-sm font-medium text-gray-300">Detected Anomalies</h2>
        </div>
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-700">
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Field</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Type</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Severity</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Score</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Count</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Detected</th>
            </tr>
          </thead>
          <tbody>
            {anomalies.map((a) => (
              <tr key={a.id} className="border-b border-gray-700/50 hover:bg-gray-700/30">
                <td className="px-6 py-4 text-sm text-white font-mono">{a.field}</td>
                <td className="px-6 py-4 text-sm text-gray-300">{a.type}</td>
                <td className="px-6 py-4 text-sm">
                  <span className={`px-2 py-1 rounded text-xs ${
                    a.severity === 'HIGH' ? 'bg-red-900/30 text-red-300' :
                    a.severity === 'MEDIUM' ? 'bg-yellow-900/30 text-yellow-300' :
                    'bg-gray-700 text-gray-300'
                  }`}>
                    {a.severity}
                  </span>
                </td>
                <td className="px-6 py-4 text-sm">
                  <div className="flex items-center gap-2">
                    <div className="w-12 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${a.score >= 0.8 ? 'bg-red-500' : a.score >= 0.6 ? 'bg-yellow-500' : 'bg-blue-500'}`}
                        style={{ width: `${a.score * 100}%` }}
                      />
                    </div>
                    <span className="text-gray-400 text-xs">{a.score.toFixed(2)}</span>
                  </div>
                </td>
                <td className="px-6 py-4 text-sm text-gray-400">{a.count}</td>
                <td className="px-6 py-4 text-sm text-gray-400">{a.detected}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
