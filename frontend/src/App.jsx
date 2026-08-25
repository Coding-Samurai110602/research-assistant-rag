import { useState } from 'react'
import Chat from './components/Chat.jsx'
import Papers from './components/Papers.jsx'
import EvalPanel from './components/EvalPanel.jsx'
import './App.css'

const TABS = [
  { id: 'chat',   label: 'Chat' },
  { id: 'papers', label: 'Papers' },
  { id: 'eval',   label: 'Eval' },
]

export default function App() {
  const [tab, setTab] = useState('chat')

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <div className="brand">
            <span className="brand-icon">⚡</span>
            <span className="brand-name">TinyML Research Assistant</span>
          </div>
          <nav className="tab-nav">
            {TABS.map(t => (
              <button
                key={t.id}
                className={`tab-btn ${tab === t.id ? 'tab-btn-active' : ''}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="app-main">
        {tab === 'chat'   && <Chat />}
        {tab === 'papers' && <Papers />}
        {tab === 'eval'   && <EvalPanel />}
      </main>
    </div>
  )
}
