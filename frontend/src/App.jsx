import { useState, useEffect, useCallback } from 'react'
import Grid from './components/Grid.jsx'
import IssueView from './components/IssueView.jsx'
import './App.css'

export default function App() {
  const [index, setIndex] = useState(null)
  const [selectedDate, setSelectedDate] = useState(null)
  const [issue, setIssue] = useState(null)
  const [loading, setLoading] = useState(true)

  const [readDates, setReadDates] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem('haaretz-read') || '[]')) }
    catch { return new Set() }
  })

  const markRead = useCallback((date) => {
    setReadDates(prev => {
      if (prev.has(date)) return prev
      const next = new Set(prev)
      next.add(date)
      localStorage.setItem('haaretz-read', JSON.stringify([...next]))
      return next
    })
  }, [])

  const toggleRead = useCallback((date) => {
    setReadDates(prev => {
      const next = new Set(prev)
      if (next.has(date)) next.delete(date); else next.add(date)
      localStorage.setItem('haaretz-read', JSON.stringify([...next]))
      return next
    })
  }, [])

  useEffect(() => {
    fetch('index.json')
      .then(r => r.json())
      .then(data => { setIndex(data); setLoading(false) })
  }, [])

  useEffect(() => {
    if (!selectedDate) { setIssue(null); return }
    setIssue(null)
    fetch(`issues/${selectedDate}.json`)
      .then(r => r.json())
      .then(setIssue)
    markRead(selectedDate)
  }, [selectedDate, markRead])

  const surpriseMe = () => {
    const issues = index?.issues || []
    if (!issues.length) return
    const unread = issues.filter(i => !readDates.has(i.magazine_date))
    const pool = unread.length ? unread : issues
    const pick = pool[Math.floor(Math.random() * pool.length)]
    setSelectedDate(pick.magazine_date)
  }

  const formatDate = (iso) => {
    const [y, m, d] = iso.split('-').map(Number)
    const months = ['','ינואר','פברואר','מרץ','אפריל','מאי','יוני','יולי','אוגוסט','ספטמבר','אוקטובר','נובמבר','דצמבר']
    return `${d} ב${months[m]} ${y}`
  }

  const readCount = (index?.issues || []).filter(i => readDates.has(i.magazine_date)).length

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="header-brand">
            <span className="header-logo">הארץ</span>
            <div>
              <h1 className="header-title">ארכיון המוסף</h1>
              {index && (
                <p className="header-sub">
                  {index.total_issues} גיליונות
                  {readCount > 0 && <span className="header-read-count"> · {readCount} נקרא</span>}
                </p>
              )}
            </div>
          </div>
          <div className="header-actions">
            {index?.last_updated && (
              <span className="header-updated">
                עודכן {new Date(index.last_updated).toLocaleDateString('he-IL')}
              </span>
            )}
            {!loading && (
              <button className="btn-surprise" onClick={surpriseMe}>
                הפתע אותי
              </button>
            )}
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
            readDates={readDates}
            onSelect={setSelectedDate}
            formatDate={formatDate}
          />
        )}

        {selectedDate && (
          <IssueView
            issue={issue}
            isRead={readDates.has(selectedDate)}
            onToggleRead={() => toggleRead(selectedDate)}
            onBack={() => setSelectedDate(null)}
            formatDate={formatDate}
          />
        )}
      </main>
    </div>
  )
}
