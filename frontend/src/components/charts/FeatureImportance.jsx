import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

export default function FeatureImportance({ features = [], topN = 20 }) {
  const data = features.slice(0, topN).map(f => ({
    name: f.name.replace(/_/g, ' '),
    value: parseFloat(f.importance.toFixed(4)),
  }))

  return (
    <div className="w-full h-96">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 160, right: 20, top: 10, bottom: 10 }}>
          <XAxis
            type="number"
            tick={{ fill: '#94A3B8', fontSize: 11 }}
            axisLine={{ stroke: '#334155' }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fill: '#94A3B8', fontSize: 11 }}
            width={155}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#0E1223',
              border: '1px solid #334155',
              borderRadius: '8px',
              fontSize: '12px',
            }}
            labelStyle={{ color: '#F8FAFC', fontWeight: 600 }}
            itemStyle={{ color: '#F59E0B' }}
          />
          <Bar dataKey="value" fill="#F59E0B" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
