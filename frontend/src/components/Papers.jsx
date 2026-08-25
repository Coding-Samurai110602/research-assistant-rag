import { useState, useEffect } from 'react'
import { getPapers } from '../api.js'

function PaperCard({ paper }) {
  return (
    <div className="paper-card">
      <a href={paper.arxiv_url} target="_blank" rel="noopener noreferrer" className="paper-title">
        {paper.title}
      </a>
      <div className="paper-authors">{paper.authors.join(', ')}</div>
      <div className="paper-meta">
        <span className="paper-id">{paper.arxiv_id}</span>
        <span className="sep">·</span>
        <span>{paper.published.slice(0, 10)}</span>
        {paper.categories.length > 0 && (
          <>
            <span className="sep">·</span>
            <span>{paper.categories.slice(0, 2).join(', ')}</span>
          </>
        )}
      </div>
    </div>
  )
}

export default function Papers() {
  const [papers, setPapers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    getPapers()
      .then(setPapers)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="loading-text">Loading papers…</div>
  if (error) return <div className="error-banner">Error: {error}</div>

  return (
    <div className="papers-layout">
      <div className="section-header">
        <h2 className="section-title">Ingested Papers</h2>
        <span className="section-count">{papers.length} papers</span>
      </div>
      <div className="papers-grid">
        {papers.map(p => (
          <PaperCard key={p.arxiv_id} paper={p} />
        ))}
      </div>
    </div>
  )
}
