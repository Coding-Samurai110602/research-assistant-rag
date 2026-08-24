"""
All LangGraph prompt templates in one place.
Import from here; never construct prompts inline in node functions.
"""

from langchain_core.prompts import ChatPromptTemplate

QUERY_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a research assistant helping answer questions about TinyML and "
        "embedded machine learning from a corpus of academic papers.\n\n"
        "Classify the user's question into one of:\n"
        "  - factual: single-paper fact lookup\n"
        "  - multi_hop: requires reasoning across ≥2 papers\n"
        "  - comparison: explicitly comparing approaches in different papers\n"
        "  - negative: likely unanswerable from a TinyML corpus (off-topic)\n\n"
        "Also rewrite the question to maximise retrieval recall: expand acronyms, "
        "add synonyms for technical terms, keep it ≤2 sentences.\n\n"
        "Respond with JSON only:\n"
        '{{ "query_type": "<type>", "rewritten_query": "<rewritten>" }}'
    ),
    ("human", "{question}"),
])

QUERY_REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "The previous retrieval attempt for the query below returned too few "
        "relevant chunks. Rewrite the query differently to improve retrieval recall.\n\n"
        "Hard constraints — you MUST follow these:\n"
        "1. Preserve every specific proper noun, paper name, arXiv ID, author name, "
        "   system name, and technical term from the original query. Do not paraphrase "
        "   or drop named entities — if the user asked about 'Pex' or '2211.17246v2', "
        "   those exact strings must appear in the rewrite.\n"
        "2. Do NOT answer the question.\n"
        "3. Return only the rewritten query string — no explanation, no JSON.\n\n"
        "Allowed changes: use alternative technical vocabulary for generic concepts, "
        "broaden or narrow scope around the named entities, add synonyms or expanded "
        "descriptions alongside (not replacing) the original terms."
    ),
    ("human", "Original query: {original_query}\nPrevious rewrite: {previous_rewrite}"),
])

RELEVANCE_GRADING_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Given a query and a retrieved passage, grade whether the passage is "
        "relevant to answering the query.\n"
        "Score: 'yes' if clearly relevant, 'no' if not.\n"
        "Be strict: a passage about general deep learning that does not specifically "
        "address the query topic should be scored 'no'.\n"
        "Return JSON only: {{ \"relevant\": \"yes\" | \"no\" }}"
    ),
    ("human", "Query: {query}\n\nPassage:\n{passage}"),
])

GENERATION_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a research assistant. Answer the question using ONLY the provided "
        "context passages. Each passage is labeled with [arxiv_id | section | page].\n\n"
        "Rules:\n"
        "1. Every factual claim in your answer must be directly and explicitly stated "
        "   in one of the passages below. Do not infer, extrapolate, or fill in details "
        "   that the passages imply but do not state.\n"
        "2. Do NOT use your own knowledge of the subject domain — not even to add "
        "   details you are confident are accurate. This applies specifically to "
        "   implementation specifics (e.g. CPU instructions, register names, hardware "
        "   behaviour, algorithm steps) that your training data covers but the passages "
        "   do not mention. If it is not in the passages, it does not belong in the answer.\n"
        "3. If a passage is ambiguous or incomplete on a detail, say so explicitly "
        "   ('the paper does not specify ...') rather than filling the gap.\n"
        "4. Cite inline using the label format: (arxiv_id, section).\n"
        "5. If the context is insufficient to answer, say exactly: "
        "   'The provided papers do not contain enough information to answer this question.'\n"
        "6. Keep the answer concise and technical, but never sacrifice grounding for brevity.\n\n"
        "Context:\n{context}"
    ),
    ("human", "{question}"),
])

GROUNDEDNESS_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Check whether every factual claim in the answer is directly supported by "
        "one of the provided context passages.\n"
        "Return JSON only:\n"
        '{{ "grounded": true | false, "note": "<brief explanation if false>" }}'
    ),
    ("human", "Answer:\n{answer}\n\nContext passages:\n{context}"),
])
