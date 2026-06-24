import { useState } from 'react'
import { Play, FileCode, Download, Clock } from 'lucide-react'

interface CleaningJob {
  id: string
  script: string
  dataset: string
  status: 'success' | 'failed' | 'running'
  rowsCleaned: number
  timestamp: string
}

export default function Cleaning() {
  const [selectedDataset, setSelectedDataset] = useState('customers.csv')
  const [generating, setGenerating] = useState(false)

  const [selectedScript] = useState(`# Auto-generated cleaning script
# Dataset: customers.csv
# Generated: 2025-01-15

import pandas as pd

def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    # Remove duplicate rows
    df = df.drop_duplicates()
    
    # Fix email format issues
    df['email'] = df['email'].str.lower().str.strip()
    
    # Handle null values in required fields
    df['name'] = df['name'].fillna('Unknown')
    
    # Remove outliers in age column
    df = df[(df['age'] >= 0) & (df['age'] <= 150)]
    
    return df
`)

  const [jobs] = useState<CleaningJob[]>([
    { id: '1', script: 'clean_customers.py', dataset: 'customers.csv', status: 'success', rowsCleaned: 1024, timestamp: '2025-01-15 08:30' },
    { id: '2', script: 'clean_orders.py', dataset: 'orders.csv', status: 'success', rowsCleaned: 512, timestamp: '2025-01-14 16:45' },
    { id: '3', script: 'clean_products.py', dataset: 'products.csv', status: 'failed', rowsCleaned: 0, timestamp: '2025-01-14 14:20' },
  ])

  const handleGenerate = () => {
    setGenerating(true)
    setTimeout(() => setGenerating(false), 1500)
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Data Cleaning</h1>
          <p className="text-gray-400 text-sm mt-1">Generate and execute auto-generated cleaning scripts</p>
        </div>
        <div className="flex gap-3">
          <select
            value={selectedDataset}
            onChange={(e) => setSelectedDataset(e.target.value)}
            className="px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="customers.csv">customers.csv</option>
            <option value="orders.csv">orders.csv</option>
            <option value="products.csv">products.csv</option>
          </select>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
          >
            <FileCode className="h-4 w-4" />
            {generating ? 'Generating...' : 'Generate Script'}
          </button>
          <button className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-2">
            <Play className="h-4 w-4" />
            Execute
          </button>
        </div>
      </div>

      {/* Script Preview */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden mb-6">
        <div className="flex items-center justify-between px-6 py-3 border-b border-gray-700">
          <div className="flex items-center gap-3">
            <FileCode className="h-4 w-4 text-gray-400" />
            <span className="text-sm text-gray-300 font-medium">clean_{selectedDataset.replace('.csv', '')}.py</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 bg-blue-900/30 text-blue-300 rounded text-xs">Python</span>
            <span className="px-2 py-0.5 bg-green-900/30 text-green-300 rounded text-xs">Ready</span>
            <button className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-700 rounded transition-colors">
              <Download className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <pre className="p-6 text-sm text-gray-300 font-mono leading-relaxed">
            {selectedScript}
          </pre>
        </div>
      </div>

      {/* Execution History */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        <div className="flex items-center gap-2 px-6 py-4 border-b border-gray-700">
          <Clock className="h-4 w-4 text-gray-400" />
          <h2 className="text-sm font-medium text-gray-300">Execution History</h2>
        </div>
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-700">
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Script</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Dataset</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Status</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Rows Cleaned</th>
              <th className="text-left px-6 py-3 text-xs font-medium text-gray-400 uppercase">Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id} className="border-b border-gray-700/50 hover:bg-gray-700/30">
                <td className="px-6 py-4 text-sm text-white font-mono">{job.script}</td>
                <td className="px-6 py-4 text-sm text-gray-300">{job.dataset}</td>
                <td className="px-6 py-4 text-sm">
                  <span className={`px-2 py-1 rounded text-xs ${
                    job.status === 'success' ? 'bg-green-900/30 text-green-300' :
                    job.status === 'failed' ? 'bg-red-900/30 text-red-300' :
                    'bg-yellow-900/30 text-yellow-300'
                  }`}>
                    {job.status}
                  </span>
                </td>
                <td className="px-6 py-4 text-sm text-gray-400">{job.rowsCleaned.toLocaleString()}</td>
                <td className="px-6 py-4 text-sm text-gray-400">{job.timestamp}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
