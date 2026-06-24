import { useState } from 'react'
import { Plus, FileText, Eye, Edit3, Send, Download } from 'lucide-react'

interface Report {
  id: string
  name: string
  type: string
  created: string
  status: 'Generated' | 'Draft' | 'Published'
}

export default function Reports() {
  const [reports] = useState<Report[]>([
    { id: '1', name: 'Weekly Quality Summary', type: 'Scheduled', created: '2025-01-15', status: 'Published' },
    { id: '2', name: 'Anomaly Report - January', type: 'On-demand', created: '2025-01-14', status: 'Generated' },
    { id: '3', name: 'Cleaning Impact Analysis', type: 'On-demand', created: '2025-01-13', status: 'Draft' },
  ])
  const [selectedReport, setSelectedReport] = useState<Report | null>(null)
  const [showEditor, setShowEditor] = useState(false)

  const reportContent = `# Weekly Quality Summary
**Period:** January 8 - January 15, 2025

## Executive Summary
Overall data quality score improved by **3.2%** this week, reaching **87%** across all monitored datasets.

## Key Metrics
| Metric | This Week | Last Week | Change |
|--------|-----------|-----------|--------|
| Quality Score | 87% | 84% | +3.2% |
| Anomalies | 47 | 62 | -24.2% |
| Rules Passed | 89% | 85% | +4.7% |
| Cleaning Jobs | 12 | 8 | +50% |

## Highlights
- \`customers.csv\` quality improved after automated cleaning
- New format validation rules reduced email anomalies by 40%
- ML model retrained with 15% lower false positive rate

## Code Example
\`\`\`python
# Quality score calculation
def calculate_score(passed: int, total: int) -> float:
    return (passed / total) * 100 if total > 0 else 0.0
\`\`\`

## Recommendations
1. Increase validation frequency for \`orders.csv\`
2. Review range constraints on \`user.age\` field
3. Schedule weekly cleaning for all production datasets
`

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Reports</h1>
          <p className="text-gray-400 text-sm mt-1">Generate, edit, and publish quality reports</p>
        </div>
        <button className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-2">
          <Plus className="h-4 w-4" />
          New Report
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Report List */}
        <div className="space-y-3">
          {reports.map((report) => (
            <div
              key={report.id}
              onClick={() => { setSelectedReport(report); setShowEditor(true) }}
              className={`bg-gray-800 rounded-xl border p-4 cursor-pointer transition-colors ${
                selectedReport?.id === report.id ? 'border-blue-500 bg-blue-900/10' : 'border-gray-700 hover:border-gray-600'
              }`}
            >
              <div className="flex items-start gap-3">
                <FileText className="h-5 w-5 text-gray-400 mt-0.5" />
                <div className="flex-1">
                  <h3 className="text-sm text-white font-medium">{report.name}</h3>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs text-gray-400">{report.type}</span>
                    <span className="text-xs text-gray-600">•</span>
                    <span className="text-xs text-gray-400">{report.created}</span>
                  </div>
                  <span className={`inline-block mt-2 px-2 py-0.5 rounded text-xs ${
                    report.status === 'Published' ? 'bg-green-900/30 text-green-300' :
                    report.status === 'Generated' ? 'bg-blue-900/30 text-blue-300' :
                    'bg-yellow-900/30 text-yellow-300'
                  }`}>
                    {report.status}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Report Viewer/Editor */}
        <div className="lg:col-span-2">
          {showEditor && selectedReport ? (
            <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
              {/* Toolbar */}
              <div className="flex items-center justify-between px-6 py-3 border-b border-gray-700">
                <h3 className="text-sm font-medium text-white">{selectedReport.name}</h3>
                <div className="flex items-center gap-2">
                  <button className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-colors">
                    <Eye className="h-4 w-4" />
                  </button>
                  <button className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-colors">
                    <Edit3 className="h-4 w-4" />
                  </button>
                  <button className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-colors">
                    <Download className="h-4 w-4" />
                  </button>
                  <button className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5">
                    <Send className="h-3 w-3" />
                    Publish
                  </button>
                </div>
              </div>

              {/* Content */}
              <div className="p-6 overflow-y-auto max-h-[600px]">
                <div className="prose prose-invert prose-sm max-w-none">
                  <pre className="whitespace-pre-wrap text-sm text-gray-300 leading-relaxed font-sans">
                    {reportContent}
                  </pre>
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-gray-800 rounded-xl border border-gray-700 p-12 flex flex-col items-center justify-center text-center">
              <FileText className="h-12 w-12 text-gray-600 mb-4" />
              <p className="text-gray-400">Select a report to view or edit</p>
              <p className="text-sm text-gray-500 mt-1">Click on any report from the list</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
