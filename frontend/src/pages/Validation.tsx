import { useState } from 'react'
import { Play, Clock } from 'lucide-react'
import QualityLineChart from '../components/Charts/QualityLineChart'
import PassFailBarChart from '../components/Charts/PassFailBarChart'

interface ValidationRun {
  id: string
  dataset: string
  status: 'passed' | 'failed' | 'running'
  score: number
  timestamp: string
  totalRules: number
  passedRules: number
}

export default function Validation() {
  const [runs] = useState<ValidationRun[]>([
    { id: '1', dataset: 'customers.csv', status: 'passed', score: 94, timestamp: '2025-01-15 10:30', totalRules: 12, passedRules: 11 },
    { id: '2', dataset: 'orders.csv', status: 'failed', score: 72, timestamp: '2025-01-15 09:15', totalRules: 8, passedRules: 6 },
    { id: '3', dataset: 'products.csv', status: 'passed', score: 100, timestamp: '2025-01-14 16:45', totalRules: 5, passedRules: 5 },
    { id: '4', dataset: 'transactions.csv', status: 'passed', score: 88, timestamp: '2025-01-14 14:20', totalRules: 10, passedRules: 9 },
    { id: '5', dataset: 'users.csv', status: 'failed', score: 65, timestamp: '2025-01-13 11:00', totalRules: 7, passedRules: 5 },
  ])

  const qualityTrend = [
    { date: 'Jan 10', score: 82 },
    { date: 'Jan 11', score: 85 },
    { date: 'Jan 12', score: 79 },
    { date: 'Jan 13', score: 83 },
    { date: 'Jan 14', score: 88 },
    { date: 'Jan 15', score: 87 },
  ]

  const barData = [
    { name: 'customers', passed: 11, failed: 1 },
    { name: 'orders', passed: 6, failed: 2 },
    { name: 'products', passed: 5, failed: 0 },
    { name: 'transactions', passed: 9, failed: 1 },
    { name: 'users', passed: 5, failed: 2 },
  ]

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Validation</h1>
          <p className="text-gray-400 text-sm mt-1">Trigger validation runs and view history</p>
        </div>
        <button className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-2">
          <Play className="h-4 w-4" />
          Run Validation
        </button>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <QualityLineChart data={qualityTrend} title="Quality Score Trend" />
        <PassFailBarChart data={barData} title="Pass/Fail by Dataset" />
      </div>

      {/* Validation History */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        <div className="flex items-center gap-2 px-6 py-4 border-b border-gray-700">
          <Clock className="h-4 w-4 text-gray-400" />
          <h2 className="text-sm font-medium text-gray-300">Validation History</h2>
        </div>
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-700">
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Dataset</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Status</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Score</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Rules</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id} className="border-b border-gray-700/50 hover:bg-gray-700/30">
                <td className="px-6 py-4 text-sm text-white font-medium">{run.dataset}</td>
                <td className="px-6 py-4 text-sm">
                  <span className={`px-2 py-1 rounded text-xs ${
                    run.status === 'passed' ? 'bg-green-900/30 text-green-300' :
                    run.status === 'failed' ? 'bg-red-900/30 text-red-300' :
                    'bg-yellow-900/30 text-yellow-300'
                  }`}>
                    {run.status}
                  </span>
                </td>
                <td className="px-6 py-4 text-sm">
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${run.score >= 90 ? 'bg-green-500' : run.score >= 70 ? 'bg-yellow-500' : 'bg-red-500'}`}
                        style={{ width: `${run.score}%` }}
                      />
                    </div>
                    <span className="text-gray-300">{run.score}%</span>
                  </div>
                </td>
                <td className="px-6 py-4 text-sm text-gray-400">{run.passedRules}/{run.totalRules}</td>
                <td className="px-6 py-4 text-sm text-gray-400">{run.timestamp}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
