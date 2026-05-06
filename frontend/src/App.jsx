import { useState, useEffect } from 'react'
import Grid from './components/Grid.jsx'
import IssueView from './components/IssueView.jsx'
import './App.css'

export default function App() {
  const [index, setIndex] = useState(null)
  const [selectedDate, setSelectedDate] = useState(null)
  const [issue, setIssue] = useState(null)
  const [loading, setLoading] = useState(true)
  const [scraping, setScraping] = useState(false)

  useEffect(() => {
    fetch('/api/issues')
      .then(r => r.json())
      .then(data => { setIndex(data); setLoading(false) })
  }, [])

  useEffect(() => {
    if (!selectedDate) { setIssue(null); return }
    setIssue(null)
    fetch(`/api/issues/${selectedDate}`)
      .then(r => r.json())
      .then(setIssue)
  }, [selectedDate])

  const handleScrape = async () => {
    setScraping(true)
    await fetch('/api/scrape', { method: 'POST' })
    setTimeout(() => {
      fetch('/api/issues').then(r => r.json()).then(data => {
        setIndex(data)
        setScraping(false)
      })
    }, 12000)
  }

  const formatDate = (iso) => {
    const [y, m, d] = iso.split('-').map(Number)
    const months = ['','ינואר','פברואר','מרץ','אפריל','מאי','יוני','יולי','אוגוסט','ספטמבר','אוקטובר','נובמבר','דצמבר']
    return `${d} ב${months[m]} ${y}`
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="header-brand">
            <span className="header-logo">הארץ</span>
            <div>
              <h1 className="header-title">ארכיון המוסף</h1>
              {index && <p className="header-sub">{index.total_issues} גיליונות</p>}
            </div>
          </div>
          <div className="header-actions">
            {index?.last_updated && (
              <span className="header-updated">
                עודכן {new Date(index.last_updated).toLocaleDateString('he-IL')}
              </span>
            )}
            <button
              className={`btn-scrape ${scraping ? 'loading' : ''}`}
              onClick={handleScrape}
              disabled={scraping}
            >
              {scraping ? 'מעדכן...' : 'עדכן ארכיון'}
            </button>
          </div>
        </div>
      </header>

      <main className="main">
        {loading && (
          <div className="spinner-wrap">
            <div className="spinner" />
            <p>טוען ארכיון...</p>
          </div>
        )}

        {!loading && !selectedDate && (
          <Grid
            issues={index?.issues || []}
            onSelect={setSelectedDate}
            formatDate={formatDate}
          />
        )}

        {selectedDate && (
          <IssueView
            issue={issue}
            onBack={() => setSelectedDate(null)}
            formatDate={formatDate}
          />
        )}
      </main>
    </div>
  )
}
