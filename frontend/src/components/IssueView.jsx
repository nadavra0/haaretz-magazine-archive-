import { useState } from 'react'
import './IssueView.css'

const SECTION_ORDER = [
  'magazine',
  'magazine/the-edge',
  'magazine/underthesun',
  'magazine/panim',
  'magazine/flights',
  'magazine/blacklist',
  'magazine/ratingcommittee',
  'magazine/on-the-line',
  'magazine/quote',
  'magazine/20questions',
  'magazine/20questions-kids',
  'magazine/ayelet-shani',
  'magazine/famous',
  'magazine/photosynthesis',
  'magazine/obit',
  'magazine/pinatlituf',
  'food/dining',
  'magazine/haaretzlogicpuzzle',
  'magazine/chess',
  'magazine/letters',
]

function sortSections(sections) {
  const entries = Object.entries(sections)
  return entries.sort(([a], [b]) => {
    const ai = SECTION_ORDER.indexOf(a)
    const bi = SECTION_ORDER.indexOf(b)
    if (ai === -1 && bi === -1) return 0
    if (ai === -1) return 1
    if (bi === -1) return -1
    return ai - bi
  })
}

function ArticleLink({ article }) {
  return (
    <a
      className="article-link"
      href={article.url}
      target="_blank"
      rel="noopener noreferrer"
    >
      {article.og_image && (
        <img
          className="article-thumb"
          src={article.og_image}
          alt=""
          loading="lazy"
        />
      )}
      <div className="article-text">
        <span className="article-title">{article.title || article.url.split('/').pop()}</span>
        <span className="article-date">{article.article_date}</span>
      </div>
    </a>
  )
}

function Section({ name, articles, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="issue-section">
      <button className="section-header" onClick={() => setOpen(o => !o)}>
        <span className="section-name">{name}</span>
        <span className="section-meta">{articles.length} כתבות</span>
        <span className={`section-chevron ${open ? 'open' : ''}`}>›</span>
      </button>
      {open && (
        <div className="section-articles">
          {articles.map(a => (
            <ArticleLink key={a.url} article={a} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function IssueView({ issue, onBack, formatDate }) {
  if (!issue) {
    return (
      <div className="issue-loading">
        <div className="spinner" />
        <p>טוען גיליון...</p>
      </div>
    )
  }

  const sorted = sortSections(issue.sections || {})

  return (
    <div className="issue-view">
      <button className="btn-back" onClick={onBack}>
        ← חזרה לארכיון
      </button>

      <div className="issue-hero">
        {issue.cover_image ? (
          <div className="hero-image-wrap">
            <img
              className="hero-image"
              src={issue.cover_image}
              alt={`שער מוסף ${formatDate(issue.magazine_date)}`}
            />
            <div className="hero-gradient" />
          </div>
        ) : (
          <div className="hero-placeholder">
            <span className="placeholder-logo-lg">הארץ</span>
            <span className="placeholder-musaf-lg">מוסף</span>
          </div>
        )}
        <div className="hero-info">
          <div className="hero-label">מוסף הארץ</div>
          <h1 className="hero-date">{formatDate(issue.magazine_date)}</h1>
          <div className="hero-stats">
            {issue.total_articles} כתבות · {sorted.length} מדורים
          </div>
        </div>
      </div>

      <div className="issue-sections">
        {sorted.map(([key, sec], i) => (
          <Section
            key={key}
            name={sec.name}
            articles={sec.articles}
            defaultOpen={i === 0}
          />
        ))}
      </div>
    </div>
  )
}
