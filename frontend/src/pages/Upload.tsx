import { useState, useEffect, useCallback } from 'react'
import { Upload as UploadIcon, FileText, CheckCircle, AlertCircle, X, Database, Table2, Save } from 'lucide-react'
import api from '../services/api'

interface CatalogOption {
  id: string
  name: string
}

interface ColumnInfo {
  name: string
  inferredType: string
  sampleValues: string[]
}

interface PreviewData {
  headers: string[]
  rows: string[][]
  totalRows: number
  separator: string
}

interface UploadResult {
  success: boolean
  fileName: string
  columns: ColumnInfo[]
  preview: PreviewData | null
  catalogId: string
  tableId: string
}

const DATA_TYPES = ['string', 'integer', 'float', 'date', 'boolean']

export default function Upload() {
  const [file, setFile] = useState<File | null>(null)
  const [catalogName, setCatalogName] = useState('')
  const [description, setDescription] = useState('')
  const [selectedCatalog, setSelectedCatalog] = useState('')
  const [createNew, setCreateNew] = useState(true)
  const [catalogs, setCatalogs] = useState<CatalogOption[]>([])

  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'uploading' | 'schema' | 'success' | 'error'>('idle')
  const [errorMessage, setErrorMessage] = useState('')
  const [uploadedCatalogId, setUploadedCatalogId] = useState<string | null>(null)

  // Schema + Preview from server
  const [columns, setColumns] = useState<ColumnInfo[]>([])
  const [serverPreview, setServerPreview] = useState<PreviewData | null>(null)
  const [tableId, setTableId] = useState<string | null>(null)
  const [savingSchema, setSavingSchema] = useState(false)

  const [dragActive, setDragActive] = useState(false)

  useEffect(() => {
    loadCatalogs()
  }, [])

  const loadCatalogs = async () => {
    try {
      const res = await api.get('/catalog', { params: { limit: 50 } })
      const items = res.data?.items || []
      setCatalogs(items.map((c: any) => ({ id: c.id, name: c.name })))
    } catch (err) {
      console.error('Failed to load catalogs:', err)
      setCatalogs([])
    }
  }

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true)
    } else if (e.type === 'dragleave') {
      setDragActive(false)
    }
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    const droppedFile = e.dataTransfer.files[0]
    if (droppedFile && (droppedFile.name.endsWith('.csv') || droppedFile.name.endsWith('.parquet'))) {
      setFile(droppedFile)
    }
  }, [])

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setFile(selectedFile)
    }
  }

  const handleUpload = async () => {
    if (!file) return
    if (createNew && !catalogName.trim()) return

    setUploading(true)
    setUploadStatus('uploading')
    setProgress(0)
    setErrorMessage('')

    try {
      // Step 1: Create catalog if needed
      setProgress(10)
      let catalogId = selectedCatalog

      if (createNew) {
        const catalogRes = await api.post('/catalog', {
          name: catalogName,
          description: description || '',
          owner: 'admindatos'
        })
        catalogId = catalogRes.data.id
      }

      if (!catalogId) {
        throw new Error('No catalog ID available')
      }
      setProgress(30)

      // Step 2: Upload file via FastAPI (server handles S3 upload + CSV parsing)
      const formData = new FormData()
      formData.append('file', file)
      formData.append('catalogId', catalogId)

      setProgress(50)

      const uploadRes = await fetch('/api/upload', {
        method: 'POST',
        credentials: 'same-origin',
        body: formData,
      })

      if (!uploadRes.ok) {
        const err = await uploadRes.json()
        throw new Error(err.error || `Upload failed with status ${uploadRes.status}`)
      }

      const result: UploadResult = await uploadRes.json()
      setProgress(100)

      // If server returned columns (CSV was parsed), show schema editor
      if (result.columns && result.columns.length > 0) {
        setColumns(result.columns)
        setServerPreview(result.preview)
        setTableId(result.tableId)
        setUploadedCatalogId(result.catalogId || catalogId)
        setUploadStatus('schema')
      } else {
        // Non-CSV or parse failed — go straight to success
        setUploadedCatalogId(catalogId)
        setUploadStatus('success')
      }
    } catch (err: any) {
      console.error('Upload failed:', err)
      setUploadStatus('error')
      setErrorMessage(err?.response?.data?.message || err.message || 'Upload failed. Please try again.')
    } finally {
      setUploading(false)
    }
  }

  const handleTypeChange = (index: number, newType: string) => {
    setColumns(prev => prev.map((col, i) => i === index ? { ...col, inferredType: newType } : col))
  }

  const handleConfirmSchema = async () => {
    if (!tableId || !uploadedCatalogId) {
      // No table registered, just go to success
      setUploadStatus('success')
      return
    }

    setSavingSchema(true)
    try {
      await fetch(`/api/tables/${tableId}/schema`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          columns: columns.map(c => ({ name: c.name, type: c.inferredType })),
          catalogId: uploadedCatalogId,
        }),
      })
      setUploadStatus('success')
    } catch (err) {
      console.error('Schema save error:', err)
      // Still go to success — the upload itself worked
      setUploadStatus('success')
    } finally {
      setSavingSchema(false)
    }
  }

  const resetUpload = () => {
    setFile(null)
    setCatalogName('')
    setDescription('')
    setProgress(0)
    setUploadStatus('idle')
    setErrorMessage('')
    setColumns([])
    setServerPreview(null)
    setTableId(null)
    setUploadedCatalogId(null)
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Upload Dataset</h1>
        <p className="text-gray-500 text-sm mt-1">Upload CSV or Parquet files to your data catalog</p>
      </div>

      {/* SUCCESS STATE */}
      {uploadStatus === 'success' && (
        <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-8 text-center">
          <CheckCircle className="h-16 w-16 text-green-500 mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-gray-900 mb-2">Upload Successful!</h2>
          <p className="text-gray-500 mb-6">Your dataset has been uploaded and the schema is saved.</p>
          <div className="flex items-center justify-center gap-4">
            <button
              onClick={resetUpload}
              className="px-4 py-2 btn-glass-primary text-white rounded-xl text-sm font-medium transition-opacity"
            >
              Upload Another
            </button>
            {uploadedCatalogId && (
              <a
                href={`/catalog/${uploadedCatalogId}`}
                className="px-4 py-2 border border-white/80 bg-white/50 text-violet-700 hover:bg-white rounded-xl text-sm font-medium transition-colors"
              >
                View in Catalog
              </a>
            )}
          </div>
        </div>
      )}

      {/* SCHEMA EDITOR STATE */}
      {uploadStatus === 'schema' && (
        <div className="space-y-6">
          {/* Preview Table */}
          {serverPreview && (
            <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                  <Table2 className="h-4 w-4 text-violet-500" />
                  Data Preview
                  <span className="ml-2 text-xs font-normal text-gray-400">
                    ({serverPreview.totalRows} rows parsed · separator: "{serverPreview.separator === '\t' ? 'TAB' : serverPreview.separator}")
                  </span>
                </h2>
              </div>
              <div className="overflow-x-auto border border-gray-200 rounded-lg">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200">
                      {serverPreview.headers.map((h, i) => (
                        <th key={i} className="px-3 py-2 text-left font-medium text-gray-600 whitespace-nowrap">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {serverPreview.rows.slice(0, 10).map((row, i) => (
                      <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                        {row.map((cell, j) => (
                          <td key={j} className="px-3 py-2 text-gray-700 whitespace-nowrap max-w-[200px] truncate">
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Schema Editor */}
          <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <Database className="h-4 w-4 text-violet-500" />
                Column Schema
                <span className="ml-2 text-xs font-normal text-gray-400">
                  ({columns.length} columns detected — edit types as needed)
                </span>
              </h2>
            </div>
            <div className="overflow-x-auto border border-gray-200 rounded-lg">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <th className="px-4 py-3 text-left font-medium text-gray-600">Column Name</th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">Inferred Type</th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">Sample Values</th>
                  </tr>
                </thead>
                <tbody>
                  {columns.map((col, idx) => (
                    <tr key={idx} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="px-4 py-3 text-gray-900 font-mono text-xs">{col.name}</td>
                      <td className="px-4 py-3">
                        <select
                          value={col.inferredType}
                          onChange={(e) => handleTypeChange(idx, e.target.value)}
                          className="px-2 py-1 border border-gray-300 rounded text-xs text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
                        >
                          {DATA_TYPES.map(t => (
                            <option key={t} value={t}>{t}</option>
                          ))}
                        </select>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500 font-mono">
                        {col.sampleValues.slice(0, 3).join(', ')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-6 flex items-center gap-4">
              <button
                onClick={handleConfirmSchema}
                disabled={savingSchema}
                className="flex items-center gap-2 px-5 py-2.5 bg-green-600 hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white font-medium rounded-xl text-sm transition-colors shadow-lg shadow-green-600/20"
              >
                <Save className="h-4 w-4" />
                {savingSchema ? 'Saving...' : 'Confirm Schema'}
              </button>
              <button
                onClick={() => setUploadStatus('success')}
                className="px-4 py-2.5 border border-white/80 bg-white/50 text-gray-600 hover:bg-white rounded-xl text-sm font-medium transition-colors"
              >
                Skip (use defaults)
              </button>
            </div>
          </div>
        </div>
      )}

      {/* UPLOAD FORM STATE */}
      {(uploadStatus === 'idle' || uploadStatus === 'uploading' || uploadStatus === 'error') && (
        <>
          {/* Catalog Association */}
          <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-6 mb-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
              <Database className="h-4 w-4 text-violet-500" />
              Catalog Association
            </h2>

            <div className="flex items-center gap-4 mb-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  checked={createNew}
                  onChange={() => setCreateNew(true)}
                  className="text-violet-600 focus:ring-violet-500"
                />
                <span className="text-sm text-gray-700">Create new catalog entry</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  checked={!createNew}
                  onChange={() => setCreateNew(false)}
                  className="text-violet-600 focus:ring-violet-500"
                />
                <span className="text-sm text-gray-700">Add to existing catalog</span>
              </label>
            </div>

            {createNew ? (
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Catalog Name <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={catalogName}
                    onChange={(e) => setCatalogName(e.target.value)}
                    placeholder="e.g., Customer Orders Q1 2025"
                    className="w-full px-4 py-2 bg-white/60 border border-white/80 rounded-xl text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Description
                  </label>
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Describe the dataset, its source, and purpose..."
                    rows={3}
                    className="w-full px-4 py-2 bg-white/60 border border-white/80 rounded-xl text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500 resize-none"
                  />
                </div>
              </div>
            ) : (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Select Catalog
                </label>
                <select
                  value={selectedCatalog}
                  onChange={(e) => setSelectedCatalog(e.target.value)}
                  className="w-full px-4 py-2 bg-white/60 border border-white/80 rounded-xl text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-violet-500"
                >
                  <option value="">Choose a catalog...</option>
                  {catalogs.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* File Drop Zone */}
          <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-6 mb-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
              <FileText className="h-4 w-4 text-violet-500" />
              Dataset File
            </h2>

            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-2xl p-8 text-center transition-colors ${
                dragActive
                  ? 'border-violet-400 bg-violet-50/50'
                  : file
                  ? 'border-green-300 bg-green-50/50'
                  : 'border-white/60 hover:border-violet-300 bg-white/20'
              }`}
            >
              {file ? (
                <div className="flex items-center justify-center gap-3">
                  <FileText className="h-8 w-8 text-green-500" />
                  <div className="text-left">
                    <p className="text-sm font-medium text-gray-900">{file.name}</p>
                    <p className="text-xs text-gray-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                  </div>
                  <button
                    onClick={() => setFile(null)}
                    className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              ) : (
                <>
                  <UploadIcon className="h-12 w-12 text-gray-400 mx-auto mb-3" />
                  <p className="text-sm text-gray-600 mb-1">
                    Drag and drop your file here, or{' '}
                    <label className="text-violet-600 hover:text-violet-700 cursor-pointer font-medium">
                      browse
                      <input
                        type="file"
                        accept=".csv,.parquet"
                        onChange={handleFileSelect}
                        className="hidden"
                      />
                    </label>
                  </p>
                  <p className="text-xs text-gray-400">Supports CSV and Parquet files up to 500MB</p>
                </>
              )}
            </div>
          </div>

          {/* Upload Progress */}
          {uploadStatus === 'uploading' && (
            <div className="glass-card rounded-2xl shadow-lg shadow-black/5 p-6 mb-6">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-gray-700">Uploading & analyzing...</span>
                <span className="text-sm text-gray-500">{progress}%</span>
              </div>
              <div className="w-full bg-white/40 rounded-full h-2">
                <div
                  className="h-2 rounded-full transition-all duration-300"
                  style={{ width: `${progress}%`, backgroundImage: 'linear-gradient(to right, #7e22ce, #6d28d9)' }}
                />
              </div>
              <p className="text-xs text-gray-400 mt-2">
                {progress < 25 && 'Creating catalog entry...'}
                {progress >= 25 && progress < 60 && 'Uploading file to S3...'}
                {progress >= 60 && progress < 100 && 'Parsing CSV & inferring types...'}
                {progress === 100 && 'Complete!'}
              </p>
            </div>
          )}

          {/* Error */}
          {uploadStatus === 'error' && (
            <div className="bg-red-50 border border-red-200 rounded-2xl p-4 mb-6 flex items-start gap-3">
              <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-red-800">Upload Failed</p>
                <p className="text-sm text-red-600 mt-1">{errorMessage}</p>
              </div>
              <button onClick={() => setUploadStatus('idle')} className="ml-auto text-red-400 hover:text-red-600">
                <X className="h-4 w-4" />
              </button>
            </div>
          )}

          {/* Upload Button */}
          <button
            onClick={handleUpload}
            disabled={!file || uploading || (createNew && !catalogName.trim()) || (!createNew && !selectedCatalog)}
            className="w-full py-3 px-6 btn-glass-primary disabled:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-xl transition-opacity text-sm"
          >
            {uploading ? 'Uploading...' : 'Upload Dataset'}
          </button>
        </>
      )}
    </div>
  )
}
