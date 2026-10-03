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
  const defaultLines = [{ dataKey: 'score', color: '#7c3aed', name: 'Quality Score' }]
  const lineConfig = lines || defaultLines

  return (
    <>
      {title && <h3 className="text-base font-bold text-gray-800 tracking-tight mb-4">{title}</h3>}
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="date" stroke="#9ca3af" fontSize={12} />
            <YAxis stroke="#9ca3af" fontSize={12} domain={[0, 100]} />
            <Tooltip
              contentStyle={{ backgroundColor: '#ffffff', border: '1px solid #e5e7eb', borderRadius: '8px', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)' }}
              labelStyle={{ color: '#374151' }}
              itemStyle={{ color: '#1f2937' }}
            />
            <Legend wrapperStyle={{ fontSize: '12px', color: '#6b7280' }} />
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
    </>
  )
}
