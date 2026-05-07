import { useState, useMemo } from 'react'
import './Grid.css'

const PLACEHOLDER_COLORS = [
  '#8B0000','#1a3a5c','#2d4a1e','#4a1e4a','#1e3a4a','#5c3d1e',
  '#2c1e5c','#1e5c3a','#5c1e1e','#3d3d1e',
]

function shortDate(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return `${String(d).padStart(2,'0')}.${String(m).padStart(2,'0')}.${y}`
}

export default function Grid({ issues, readDates = new Set(), onSelect, formatDate }) {
  const years = useMemo(() => {
    const ys = [...new Set(issues.map(i => i.magazine_date.slice(0, 4)))].sort().reverse()
    return ys
  }, [issues])

  const [selectedYear, setSelectedYear] = useState('all')

  const filtered = useMemo(
    () => selectedYear === 'all' ? issues : issues.filter(i => i.magazine_date.startsWith(selectedYear)),
    [issues, selectedYear]
  )

  if (!issues.length) {
    return (
      <div className="grid-empty">
        <p>הארכיון ריק — לחץ "עדכן ארכיון" כדי לאחזר גיליונות.</p>
      </div>
    )
  }

  return (
    <div>
      <div className="year-tabs">
        {years.map(y => (
          <button
            key={y}
            className={`year-tab ${y === selectedYear ? 'active' : ''}`}
            onClick={() => setSelectedYear(y === selectedYear ? 'all' : y)}
          >
            {y}
          </button>
        ))}
      </div>
      <div className="grid-heading">
        <h2>{selectedYear === 'all' ? 'כל הגיליונות' : `גיליונות ${selectedYear}`}</h2>
        <span className="grid-count">{filtered.length} מוספים</span>
      </div>
      <div className="grid">
        {filtered.map((issue, i) => (
          <button
            key={issue.magazine_date}
            className="card"
            onClick={() => onSelect(issue.magazine_date)}
          >
            <div className="card-image">
              {issue.cover_image ? (
                <img
                  src={issue.cover_image}
                  alt={`שער מוסף ${shortDate(issue.magazine_date)}`}
                  loading="lazy"
                />
              ) : (
                <div
                  className="card-placeholder"
                  style={{ background: PLACEHOLDER_COLORS[i % PLACEHOLDER_COLORS.length] }}
                >
                  <span className="placeholder-logo">הארץ</span>
                  <span className="placeholder-musaf">מוסף</span>
                </div>
              )}
              <div className="card-overlay" />
              {readDates.has(issue.magazine_date) && (
                <div className="card-read-badge" title="נקרא">✓</div>
              )}
            </div>
            <div className="card-footer">
              <div className="card-date">{formatDate(issue.magazine_date)}</div>
              <div className="card-meta">
                {issue.total_articles} כתבות · {issue.section_count} מדורים
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
