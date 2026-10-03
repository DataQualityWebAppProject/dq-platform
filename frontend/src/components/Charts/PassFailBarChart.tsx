import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'

interface DataPoint {
  name: string
  passed: number
  failed: number
}

interface PassFailBarChartProps {
  data: DataPoint[]
  title?: string
}

export default function PassFailBarChart({ data, title }: PassFailBarChartProps) {
  return (
    <>
      {title && <h3 className="text-base font-bold text-gray-800 tracking-tight mb-4">{title}</h3>}
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="name" stroke="#9ca3af" fontSize={12} />
            <YAxis stroke="#9ca3af" fontSize={12} />
            <Tooltip
              contentStyle={{ backgroundColor: '#ffffff', border: '1px solid #e5e7eb', borderRadius: '8px', boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)' }}
              labelStyle={{ color: '#374151' }}
              itemStyle={{ color: '#1f2937' }}
            />
            <Legend wrapperStyle={{ fontSize: '12px', color: '#6b7280' }} />
            <Bar dataKey="passed" fill="#22c55e" name="Passed" radius={[4, 4, 0, 0]} />
            <Bar dataKey="failed" fill="#ef4444" name="Failed" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  )
}
