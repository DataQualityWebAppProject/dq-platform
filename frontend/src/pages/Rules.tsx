import { useState, useEffect } from 'react'
import { Wand2, Plus, Trash2, ChevronDown, Loader2 } from 'lucide-react'
import api from '../services/api'

interface Rule {
  id: string
  name: string
  type: string
  expression: string
  status: 'active' | 'draft' | 'disabled'
  catalogId?: string
  catalogName?: string
  tableName?: string
  columnName?: string
  generatedCode?: string
  generatingCode?: boolean
}

interface CatalogOption {
  id: string
  name: string
}

interface TableOption {
  name: string
  columns: string[]
}

export default function Rules() {
  const [nlInput, setNlInput] = useState('')
  const [generating, setGenerating] = useState(false)
  const [rules, setRules] = useState<Rule[]>([])

  // Scope selectors state
  const [selectedCatalog, setSelectedCatalog] = useState('')
  const [selectedTable, setSelectedTable] = useState('')
  const [selectedColumn, setSelectedColumn] = useState('')

  // Available options for scope
  const [catalogs, setCatalogs] = useState<CatalogOption[]>([])
  const [tables, setTables] = useState<TableOption[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [loadingCatalogs, setLoadingCatalogs] = useState(false)
  const [loadingTables, setLoadingTables] = useState(false)

  useEffect(() => {
    loadCatalogs()
    loadRules()
  }, [])

  useEffect(() => {
    if (selectedCatalog) {
      loadTables(selectedCatalog)
    } else {
      setTables([])
      setSelectedTable('')
      setSelectedColumn('')
    }
  }, [selectedCatalog])

  useEffect(() => {
    if (selectedTable) {
      const table = tables.find(t => t.name === selectedTable)
      setColumns(table?.columns || [])
    } else {
      setColumns([])
      setSelectedColumn('')
    }
  }, [selectedTable, tables])

  const loadCatalogs = async () => {
    setLoadingCatalogs(true)
    try {
      const res = await api.get('/catalog', { params: { limit: 50 } })
      const items = res.data?.items || []
      setCatalogs(items.map((c: any) => ({ id: c.id, name: c.name })))
    } catch (err) {
      console.error('Failed to load catalogs:', err)
      setCatalogs([])
    } finally {
      setLoadingCatalogs(false)
    }
  }

  const loadRules = async () => {
    try {
      const res = await api.get('/rules', { params: { limit: 50 } })
      const items = res.data?.items || []
      if (items.length > 0) {
        const loadedRules = items.map((r: any) => ({
          id: r.id || String(Date.now()),
          name: r.naturalLanguage?.substring(0, 60) || 'Rule',
          type: (r.templateCategory || r.scope || 'simple').toUpperCase(),
          expression: r.naturalLanguage || '',
          status: r.status || 'active',
          catalogId: r.catalogId || '',
          catalogName: '',
          tableName: r.tableId || '',
          columnName: r.columnId || '',
          generatedCode: '',
          generatingCode: true, // will auto-generate
        }))
        setRules(loadedRules)

        // Auto-generate code for all loaded rules
        for (const rule of loadedRules) {
          api.post(`/rules/${rule.id}/generate-code`).then(res => {
            const code = res.data?.code || res.data?.script || ''
            setRules(prev => prev.map(r => r.id === rule.id ? { ...r, generatedCode: code, generatingCode: false } : r))
          }).catch(() => {
            setRules(prev => prev.map(r => r.id === rule.id ? { ...r, generatingCode: false } : r))
          })
        }
      }
    } catch (err) {
      console.error('Failed to load rules:', err)
    }
  }

  const loadTables = async (catalogId: string) => {
    setLoadingTables(true)
    setSelectedTable('')
    setSelectedColumn('')
    try {
      const res = await api.get(`/catalog/${catalogId}/tables`)
      const items = res.data?.items || []
      setTables(items.map((t: any) => ({
        name: t.name || t.fileName || '',
        columns: (t.columns || []).map((c: any) => typeof c === 'string' ? c : c.name),
      })))
    } catch (err) {
      console.error('Failed to load tables:', err)
      setTables([])
    } finally {
      setLoadingTables(false)
    }
  }

  const generateCodeForRule = async (ruleId: string) => {
    setRules(prev => prev.map(r => r.id === ruleId ? { ...r, generatingCode: true } : r))
    try {
      const res = await api.post(`/rules/${ruleId}/generate-code`)
      const code = res.data?.code || res.data?.script || ''
      setRules(prev => prev.map(r => r.id === ruleId ? { ...r, generatedCode: code, generatingCode: false } : r))
    } catch (err) {
      console.error('Code generation failed:', err)
      setRules(prev => prev.map(r => r.id === ruleId ? { ...r, generatingCode: false } : r))
    }
  }

  const handleGenerate = async () => {
    if (!nlInput.trim()) return
    if (!selectedCatalog) return
    setGenerating(true)

    const catalogName = catalogs.find(c => c.id === selectedCatalog)?.name || ''

    try {
      const res = await api.post('/rules/interpret', {
        naturalLanguage: nlInput,
        scope: selectedColumn ? 'column' : selectedTable ? 'table' : 'catalog',
        catalogId: selectedCatalog,
        tableId: selectedTable || undefined,
        columnId: selectedColumn || undefined,
      })
      if (res.data) {
        const interpreted = res.data

        const newRule: Rule = {
          id: String(Date.now()),
          name: interpreted.preview?.ruleName || nlInput.substring(0, 50),
          type: interpreted.structuredJson?.type?.toUpperCase() || 'NL_GENERATED',
          expression: interpreted.preview?.expectedBehavior || interpreted.preview?.conditions || '',
          status: 'active',
          catalogId: selectedCatalog,
          catalogName,
          tableName: selectedTable,
          columnName: selectedColumn,
          generatedCode: '',
          generatingCode: true,
        }

        // Persist rule to backend
        let savedRuleId = ''
        try {
          const saveRes = await api.post('/rules', {
            naturalLanguage: nlInput,
            scope: selectedColumn ? 'column' : selectedTable ? 'table' : 'catalog',
            catalogId: selectedCatalog,
            tableId: selectedTable || undefined,
            columnId: selectedColumn || undefined,
            structuredJson: interpreted.structuredJson,
            templateCategory: interpreted.structuredJson?.type || 'simple',
            status: 'active',
          })
          savedRuleId = saveRes.data?.id || saveRes.data?.ruleId || ''
          if (savedRuleId) {
            newRule.id = savedRuleId
          }
        } catch (saveErr: any) {
          if (saveErr?.response?.status === 409) {
            const existingText = saveErr.response.data?.existingRuleText || ''
            alert(`This rule already exists on this column:\n\n"${existingText}"\n\nA rule cannot be duplicated on the same column.`)
            setGenerating(false)
            setNlInput('')
            return
          }
          console.warn('Rule persistence failed:', saveErr)
        }

        setRules([newRule, ...rules])

        // Generate Python code in background
        const ruleIdForCode = savedRuleId || newRule.id
        try {
          const codeRes = await api.post(`/rules/${ruleIdForCode}/generate-code`)
          const code = codeRes.data?.script || codeRes.data?.code || ''
          setRules(prev => prev.map(r => r.id === ruleIdForCode ? { ...r, generatedCode: code, generatingCode: false } : r))
        } catch {
          setRules(prev => prev.map(r => r.id === ruleIdForCode ? { ...r, generatingCode: false } : r))
        }
      }
    } catch (err: any) {
      alert(`Error: ${err?.response?.data?.error || err?.message || 'Unknown error'}`)
    } finally {
      setNlInput('')
      setGenerating(false)
    }
  }

  const deleteRule = (id: string) => {
    setRules(rules.filter((r) => r.id !== id))
  }

  const getScopeLabel = (rule: Rule) => {
    const parts = [rule.catalogName, rule.tableName, rule.columnName].filter(Boolean)
    return parts.join(' → ')
  }

  const typeColors: Record<string, string> = {
    FORMAT: 'bg-fuchsia-100 text-fuchsia-700',
    RANGE: 'bg-violet-100 text-violet-700',
    COMPLETENESS: 'bg-green-100 text-green-700',
    SIMPLE: 'bg-gray-100 text-gray-600',
    NL_GENERATED: 'bg-amber-100 text-amber-700',
    CUSTOM: 'bg-amber-100 text-amber-700',
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Quality Rules</h1>
          <p className="text-gray-500 text-sm mt-1">Define and manage data quality rules with natural language</p>
        </div>
      </div>

      {/* NL Rule Generation with 3-Level Scope Selector */}
      <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-6 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <Wand2 className="h-4 w-4 text-violet-500" />
          <h2 className="text-sm font-semibold text-gray-700">Generate Rule from Natural Language</h2>
        </div>

        {/* 3-Level Scope Selector */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Catalog <span className="text-red-500">*</span>
            </label>
            <div className="relative">
              <select
                value={selectedCatalog}
                onChange={(e) => setSelectedCatalog(e.target.value)}
                className="w-full px-3 py-2 bg-white/60 border border-white/80 rounded-xl text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-violet-500 appearance-none"
                disabled={loadingCatalogs}
              >
                <option value="">Select catalog...</option>
                {catalogs.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Table</label>
            <div className="relative">
              <select
                value={selectedTable}
                onChange={(e) => setSelectedTable(e.target.value)}
                className="w-full px-3 py-2 bg-white/60 border border-white/80 rounded-xl text-sm appearance-none disabled:bg-gray-100/60 disabled:text-gray-400"
                disabled={!selectedCatalog || loadingTables}
              >
                <option value="">{loadingTables ? 'Loading...' : 'Select table...'}</option>
                {tables.map((t) => (
                  <option key={t.name} value={t.name}>{t.name}</option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Column</label>
            <div className="relative">
              <select
                value={selectedColumn}
                onChange={(e) => setSelectedColumn(e.target.value)}
                className="w-full px-3 py-2 bg-white/60 border border-white/80 rounded-xl text-sm appearance-none disabled:bg-gray-100/60 disabled:text-gray-400"
                disabled={!selectedTable}
              >
                <option value="">All columns (table-level)</option>
                {columns.map((col) => (
                  <option key={col} value={col}>{col}</option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            </div>
          </div>
        </div>

        {/* Scope indicator */}
        {selectedCatalog && (
          <div className="mb-4 text-xs text-gray-500">
            <span className="font-medium">Scope:</span>{' '}
            <span className="text-gray-700">
              {catalogs.find(c => c.id === selectedCatalog)?.name}
              {selectedTable && ` → ${selectedTable}`}
              {selectedColumn && ` → ${selectedColumn}`}
            </span>
          </div>
        )}

        {/* NL Input */}
        <div className="flex gap-3">
          <input
            type="text"
            value={nlInput}
            onChange={(e) => setNlInput(e.target.value)}
            placeholder="e.g., 'ABONO must be greater than zero' or 'TDOC_DOCU cannot be null'"
            className="flex-1 px-4 py-2.5 bg-white/60 border border-white/80 rounded-xl text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500 text-sm"
            onKeyDown={(e) => e.key === 'Enter' && handleGenerate()}
            disabled={generating}
          />
          <button
            onClick={handleGenerate}
            disabled={generating || !nlInput.trim() || !selectedCatalog}
            className="px-6 py-2.5 btn-glass-primary disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl text-sm font-medium transition-opacity flex items-center gap-2"
          >
            <Wand2 className="h-4 w-4" />
            {generating ? 'Generating...' : 'Generate'}
          </button>
        </div>
        {!selectedCatalog && (
          <p className="text-xs text-red-500 mt-2">Select a catalog first</p>
        )}
      </div>

      {/* Rules List */}
      <div className="space-y-3">
        {rules.length === 0 && (
          <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-8 text-center">
            <p className="text-gray-500">No rules yet. Use the form above to create one.</p>
          </div>
        )}
        {rules.map((rule) => (
          <div key={rule.id} className="glass-card rounded-2xl shadow-lg shadow-black/5 p-5 hover:shadow-xl hover:shadow-black/10 transition-all">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3 flex-wrap">
                <h3 className="text-gray-900 font-medium text-sm">{rule.name}</h3>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${typeColors[rule.type] || 'bg-gray-100 text-gray-600'}`}>
                  {rule.type}
                </span>
                <span className="px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                  {rule.status}
                </span>
              </div>
              <button
                onClick={() => deleteRule(rule.id)}
                className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>

            {getScopeLabel(rule) && (
              <p className="text-xs text-gray-500 mb-2">
                <span className="font-medium">Scope:</span> {getScopeLabel(rule)}
              </p>
            )}

            {/* Python Code Section */}
            <div className="mt-3">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Python Validation Code</p>
              {rule.generatingCode ? (
                <div className="flex items-center gap-2 px-3 py-2 bg-violet-50 border border-violet-200 rounded-xl">
                  <Loader2 className="h-3 w-3 animate-spin text-violet-600" />
                  <p className="text-xs text-violet-700">Generating Python code with AI...</p>
                </div>
              ) : rule.generatedCode ? (
                <pre className="bg-gray-900 text-green-400 p-4 rounded-lg text-xs overflow-x-auto">
                  <code>{rule.generatedCode}</code>
                </pre>
              ) : (
                <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg">
                  <Loader2 className="h-3 w-3 animate-spin text-gray-500" />
                  <p className="text-xs text-gray-500">Loading code...</p>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
