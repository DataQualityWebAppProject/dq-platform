import { RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip } from 'recharts'

interface DataPoint {
  field: string
  count: number
  fullMark?: number
}

interface AnomalyRadarChartProps {
  data: DataPoint[]
  title?: string
}

export default function AnomalyRadarChart({ data, title }: AnomalyRadarChartProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
      {title && <h3 className="text-sm font-semibold text-gray-700 mb-4">{title}</h3>}
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
            <PolarGrid stroke="#e5e7eb" />
            <PolarAngleAxis dataKey="field" stroke="#6b7280" fontSize={11} />
            <PolarRadiusAxis stroke="#d1d5db" fontSize={10} />
            <Tooltip
              contentStyle={{ backgroundColor: '#ffffff', border: '1px solid #e5e7eb', borderRadius: '8px', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)' }}
              labelStyle={{ color: '#374151' }}
              itemStyle={{ color: '#1f2937' }}
            />
            <Radar
              name="Anomalies"
              dataKey="count"
              stroke="#f59e0b"
              fill="#f59e0b"
              fillOpacity={0.3}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
