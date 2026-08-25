import { useState, useRef, useEffect } from 'react'
import { queryAPI } from '../api.js'

function CitationCard({ citation, index }) {
  const arxivUrl = `https://arxiv.org/abs/${citation.arxiv_id}`
  return (
    <div className="citation-card">
      <span className="citation-index">[{index + 1}]</span>
      <div className="citation-body">
        <a href={arxivUrl} target="_blank" rel="noopener noreferrer" className="citation-title">
          {citation.title}
        </a>
        <div className="citation-meta">
          <span>{citation.arxiv_id}</span>
          <span className="sep">·</span>
          <span>{citation.section_title}</span>
          <span className="sep">·</span>
          <span>p. {citation.page}</span>
        </div>
      </div>
    </div>
  )
}

function Exchange({ item }) {
  const { question, response } = item

  const groundednessClass = response.is_grounded ? 'badge badge-ok' : 'badge badge-warn'
  const answerableClass = response.answerable ? '' : 'declined'

  return (
    <div className="exchange">
      <div className="bubble user-bubble">
        <span className="bubble-label">You</span>
        <p>{question}</p>
      </div>

      <div className={`bubble assistant-bubble ${answerableClass}`}>
        <span className="bubble-label">
          Assistant
          {response.query_type && (
            <span className="badge badge-type">{response.query_type}</span>
          )}
          <span className={groundednessClass}>
            {response.is_grounded ? 'grounded' : 'ungrounded'}
          </span>
        </span>

        {!response.answerable ? (
          <p className="declined-text">
            The system declined to answer — this question appears to be outside the scope of
            the ingested corpus.
          </p>
        ) : (
          <p className="answer-text">{response.answer}</p>
        )}

        {response.groundedness_note && (
          <p className="groundedness-note">{response.groundedness_note}</p>
        )}

        {response.citations.length > 0 && (
          <div className="citations-section">
            <div className="citations-label">Sources</div>
            {response.citations.map((c, i) => (
              <CitationCard key={c.chunk_id} citation={c} index={i} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function Chat() {
  const [exchanges, setExchanges] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [exchanges, loading])

  async function handleSubmit(e) {
    e.preventDefault()
    const question = input.trim()
    if (!question || loading) return

    setInput('')
    setError(null)
    setLoading(true)

    try {
      const response = await queryAPI(question)
      setExchanges(prev => [...prev, { question, response }])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="chat-layout">
      <div className="messages">
        {exchanges.length === 0 && !loading && (
          <div className="empty-state">
            Ask a question about the 15 ingested TinyML papers.
          </div>
        )}
        {exchanges.map((item, i) => (
          <Exchange key={i} item={item} />
        ))}
        {loading && (
          <div className="bubble assistant-bubble loading-bubble">
            <span className="bubble-label">Assistant</span>
            <span className="spinner" />
          </div>
        )}
        {error && (
          <div className="error-banner">Error: {error}</div>
        )}
        <div ref={bottomRef} />
      </div>

      <form className="input-row" onSubmit={handleSubmit}>
        <input
          className="question-input"
          type="text"
          placeholder="Ask about TinyML, model compression, edge inference…"
          value={input}
          onChange={e => setInput(e.target.value)}
          disabled={loading}
          autoFocus
        />
        <button className="submit-btn" type="submit" disabled={loading || !input.trim()}>
          {loading ? '…' : 'Ask'}
        </button>
      </form>
    </div>
  )
}
