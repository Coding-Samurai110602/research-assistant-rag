const BASE = 'http://localhost:8000'

/**
 * POST /query
 * Returns QueryResponse: { answer, citations, retrieved_chunk_ids, retry_count,
 *   answerable, is_grounded, groundedness_note, query_type, rewritten_query }
 * Each citation: { arxiv_id, title, section_title, page, chunk_id }
 * Note: citation.text is stripped by the API layer (not returned).
 */
export async function queryAPI(question) {
  const res = await fetch(`${BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

/** GET /papers — returns PaperOut[]: { arxiv_id, title, authors, published, categories, arxiv_url } */
export async function getPapers() {
  const res = await fetch(`${BASE}/papers`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
