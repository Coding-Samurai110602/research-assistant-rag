import { useState, useEffect } from 'react'

function MetricBar({ score }) {
  const pct = Math.round(score * 100)
  const color = pct >= 70 ? '#22c55e' : pct >= 45 ? '#f59e0b' : '#ef4444'
  return (
    <div className="metric-bar-track">
      <div className="metric-bar-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  )
}

function MetricRow({ metric }) {
  const [open, setOpen] = useState(false)
  const pct = Math.round(metric.score * 100)
  return (
    <div className="metric-row">
      <div className="metric-top" onClick={() => setOpen(o => !o)} style={{ cursor: 'pointer' }}>
        <span className="metric-name">{metric.name}</span>
        <MetricBar score={metric.score} />
        <span className="metric-score">{pct}%</span>
        <span className="metric-toggle">{open ? '▲' : '▼'}</span>
      </div>
      {open && <p className="metric-desc">{metric.description}</p>}
    </div>
  )
}

export default function EvalPanel() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/eval_summary.json')
      .then(r => r.json())
      .then(setData)
      .catch(err => setError(err.message))
  }, [])

  if (error) return <div className="error-banner">Error loading eval data: {error}</div>
  if (!data) return <div className="loading-text">Loading…</div>

  return (
    <div className="eval-layout">
      <div className="section-header">
        <h2 className="section-title">RAGAS Evaluation Results</h2>
        <span className="section-count">{data.dataset}</span>
      </div>

      <div className="eval-metrics">
        {data.metrics.map(m => (
          <MetricRow key={m.name} metric={m} />
        ))}
      </div>

      {data.note && (
        <div className="eval-note">
          <strong>Note:</strong> {data.note}
        </div>
      )}
    </div>
  )
}
