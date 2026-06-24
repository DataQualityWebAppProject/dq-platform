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
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-6">
      {title && <h3 className="text-sm font-medium text-gray-300 mb-4">{title}</h3>}
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
            <PolarGrid stroke="#374151" />
            <PolarAngleAxis dataKey="field" stroke="#9ca3af" fontSize={11} />
            <PolarRadiusAxis stroke="#4b5563" fontSize={10} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
              labelStyle={{ color: '#9ca3af' }}
              itemStyle={{ color: '#e5e7eb' }}
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
