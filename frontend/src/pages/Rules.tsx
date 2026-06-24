import { useState } from 'react'
import { Wand2, Plus, Trash2, Pencil } from 'lucide-react'
import api from '../services/api'

interface Rule {
  id: string
  name: string
  type: string
  expression: string
  status: 'active' | 'draft' | 'disabled'
}

export default function Rules() {
  const [nlInput, setNlInput] = useState('')
  const [generating, setGenerating] = useState(false)
  const [rules, setRules] = useState<Rule[]>([
    { id: '1', name: 'Email format check', type: 'FORMAT', expression: 'field.email MATCHES /^[^@]+@[^@]+$/', status: 'active' },
    { id: '2', name: 'Age range validation', type: 'RANGE', expression: 'field.age BETWEEN 0 AND 150', status: 'active' },
    { id: '3', name: 'Non-null ID', type: 'COMPLETENESS', expression: 'field.id IS NOT NULL', status: 'active' },
    { id: '4', name: 'Phone format', type: 'FORMAT', expression: 'field.phone MATCHES /^\\+?[0-9]{10,15}$/', status: 'draft' },
    { id: '5', name: 'Amount positive', type: 'RANGE', expression: 'field.amount > 0', status: 'active' },
  ])

  const handleGenerate = async () => {
    if (!nlInput.trim()) return
    setGenerating(true)

    try {
      const res = await api.post('/governance/rules/generate', { prompt: nlInput })
      if (res.data) {
        setRules([{ id: String(Date.now()), ...res.data, status: 'draft' }, ...rules])
      }
    } catch {
      // Fallback: create a mock generated rule
      const newRule: Rule = {
        id: String(Date.now()),
        name: nlInput,
        type: 'NL_GENERATED',
        expression: `/* Generated from: "${nlInput}" */`,
        status: 'draft',
      }
      setRules([newRule, ...rules])
    } finally {
      setNlInput('')
      setGenerating(false)
    }
  }

  const deleteRule = (id: string) => {
    setRules(rules.filter((r) => r.id !== id))
  }

  const typeColors: Record<string, string> = {
    FORMAT: 'bg-purple-900/30 text-purple-300',
    RANGE: 'bg-blue-900/30 text-blue-300',
    COMPLETENESS: 'bg-green-900/30 text-green-300',
    NL_GENERATED: 'bg-amber-900/30 text-amber-300',
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Quality Rules</h1>
          <p className="text-gray-400 text-sm mt-1">Define and manage data quality rules with natural language</p>
        </div>
        <button className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-2">
          <Plus className="h-4 w-4" />
          Manual Rule
        </button>
      </div>

      {/* NL Rule Generation */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 p-6 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <Wand2 className="h-4 w-4 text-amber-400" />
          <h2 className="text-sm font-medium text-gray-300">Generate Rule from Natural Language</h2>
        </div>
        <div className="flex gap-3">
          <input
            type="text"
            value={nlInput}
            onChange={(e) => setNlInput(e.target.value)}
            placeholder="e.g., 'Ensure email field is not empty and matches standard email format'"
            className="flex-1 px-4 py-2.5 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
            onKeyDown={(e) => e.key === 'Enter' && handleGenerate()}
            disabled={generating}
          />
          <button
            onClick={handleGenerate}
            disabled={generating || !nlInput.trim()}
            className="px-6 py-2.5 bg-amber-600 hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
          >
            <Wand2 className="h-4 w-4" />
            {generating ? 'Generating...' : 'Generate'}
          </button>
        </div>
      </div>

      {/* Rules List */}
      <div className="space-y-3">
        {rules.map((rule) => (
          <div key={rule.id} className="bg-gray-800 rounded-xl border border-gray-700 p-5 hover:border-gray-600 transition-colors">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <h3 className="text-white font-medium">{rule.name}</h3>
                <span className={`px-2 py-0.5 rounded text-xs ${typeColors[rule.type] || 'bg-gray-700 text-gray-300'}`}>
                  {rule.type}
                </span>
                <span className={`px-2 py-0.5 rounded text-xs ${
                  rule.status === 'active' ? 'bg-green-900/30 text-green-300' :
                  rule.status === 'draft' ? 'bg-yellow-900/30 text-yellow-300' :
                  'bg-gray-700 text-gray-400'
                }`}>
                  {rule.status}
                </span>
              </div>
              <div className="flex items-center gap-1">
                <button className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-colors">
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={() => deleteRule(rule.id)}
                  className="p-2 text-gray-400 hover:text-red-400 hover:bg-red-900/20 rounded-lg transition-colors"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
            <code className="text-sm text-gray-400 bg-gray-900 px-3 py-1.5 rounded block font-mono">{rule.expression}</code>
          </div>
        ))}
      </div>
    </div>
  )
}
