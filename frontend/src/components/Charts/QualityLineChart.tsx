import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'

interface DataPoint {
  date: string
  score: number
  [key: string]: string | number
}

interface QualityLineChartProps {
  data: DataPoint[]
  title?: string
  lines?: { dataKey: string; color: string; name: string }[]
}

export default function QualityLineChart({ data, title, lines }: QualityLineChartProps) {
  const defaultLines = [{ dataKey: 'score', color: '#3b82f6', name: 'Quality Score' }]
  const lineConfig = lines || defaultLines

  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-6">
      {title && <h3 className="text-sm font-medium text-gray-300 mb-4">{title}</h3>}
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis dataKey="date" stroke="#6b7280" fontSize={12} />
            <YAxis stroke="#6b7280" fontSize={12} domain={[0, 100]} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
              labelStyle={{ color: '#9ca3af' }}
              itemStyle={{ color: '#e5e7eb' }}
            />
            <Legend wrapperStyle={{ fontSize: '12px', color: '#9ca3af' }} />
            {lineConfig.map((line) => (
              <Line
                key={line.dataKey}
                type="monotone"
                dataKey={line.dataKey}
                stroke={line.color}
                name={line.name}
                strokeWidth={2}
                dot={{ fill: line.color, r: 3 }}
                activeDot={{ r: 5 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
