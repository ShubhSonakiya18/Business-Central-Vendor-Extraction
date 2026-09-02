import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import NavBar from '../components/NavBar'
import Stepper from '../components/Stepper'
import './CustomerReviewPage.css'

const CUSTOMER_STEPS = [{ label: 'Upload' }, { label: 'Review' }, { label: 'Submit' }]

const DocsIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
    <line x1="16" y1="13" x2="8" y2="13" />
    <line x1="16" y1="17" x2="8" y2="17" />
    <polyline points="10 9 9 9 8 9" />
  </svg>
)

/**
 * Convert a confidence float (0–1) into a display percentage and tier.
 * Backend may return 0-1 floats or 0-100 integers — normalise both.
 */
function parseConf(raw) {
  if (raw == null) return { pct: null, low: false }
  const pct = raw > 1 ? Math.round(raw) : Math.round(raw * 100)
  return { pct, low: pct < 85 }
}

/**
 * Build a flat list of { id, label, value, conf, low, fullWidth } rows from
 * the backend fields map.
 */
function buildFields(fields, needsReview) {
  const reviewSet = new Set(needsReview ?? [])
  // Fields that span both grid columns (addresses, long free-text)
  const FULL_WIDTH_KEYS = new Set([
    'billing_address', 'address', 'billing address', 'address 1',
    'type', 'type (services / license)', 'services',
  ])

  return Object.entries(fields ?? {}).map(([key, field]) => {
    const { pct, low } = parseConf(field.confidence)
    const isLow = low || reviewSet.has(key)
    const label = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    const fullWidth = FULL_WIDTH_KEYS.has(key.toLowerCase())

    return {
      id: key,
      label,
      value: field.value ?? '',
      pct,
      low: isLow,
      fullWidth,
    }
  })
}

export default function CustomerReviewPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [loading, setLoading] = useState(false)

  const result = location.state?.result

  // Redirect if landed here without going through upload
  if (!result) {
    return (
      <>
        <NavBar />
        <div className="page-wrapper">
          <main className="page-content">
            <p style={{ color: 'var(--color-text-muted)', marginTop: 40 }}>
              No extraction data found.{' '}
              <a className="back-link" onClick={() => navigate('/customer/upload')} style={{ cursor: 'pointer', display: 'inline' }}>
                Go back to Upload
              </a>
            </p>
          </main>
        </div>
      </>
    )
  }

  const fieldDefs = buildFields(result.fields, result.needs_review)
  const [fieldValues, setFieldValues] = useState(
    Object.fromEntries(fieldDefs.map(f => [f.id, f.value]))
  )

  const uploadedFiles = result.documents ?? []

  function handleSubmit() {
    setLoading(true)
    setTimeout(() => navigate('/customer/confirm', { state: { result } }), 1000)
  }

  return (
    <>
      <NavBar />
      <div className="page-wrapper">
        <main className="page-content">

          <a className="back-link" onClick={() => navigate('/customer/upload')} style={{ cursor: 'pointer' }}>
            ‹ Upload
          </a>

          <h1 className="page-title">Customer Creation</h1>

          {/* Extraction summary */}
          {result.timings && (
            <p style={{ fontSize: '0.8rem', color: 'var(--color-text-subtle)', marginBottom: 4 }}>
              Extracted {result.summary?.filled ?? 0}/{result.summary?.total_fields ?? 0} fields
              in {result.timings.total}s
            </p>
          )}

          <Stepper steps={CUSTOMER_STEPS} currentStep={1} />

          <div className="review-card" role="region" aria-label="Extracted Customer Fields">

            {fieldDefs.length > 0 ? (
              <div className="fields-grid">
                {fieldDefs.map(f => (
                  <div
                    key={f.id}
                    className={`form-group${f.fullWidth ? ' field-span-full' : ''}`}
                    style={{ marginBottom: 0 }}
                  >
                    <div className="field-header">
                      <label
                        className="field-label"
                        htmlFor={f.id}
                        style={f.low ? { color: 'var(--color-warning)' } : undefined}
                      >
                        {f.label}
                      </label>
                      {f.pct != null && (
                        <span
                          className={`conf-badge ${f.low ? 'conf-low' : 'conf-high'}`}
                          title={`${f.pct}% confidence`}
                        >
                          {f.pct}% {f.low ? 'review' : 'match'}
                        </span>
                      )}
                    </div>
                    <input
                      id={f.id}
                      type="text"
                      className={`form-input${f.low ? ' input-low-confidence' : ''}`}
                      value={fieldValues[f.id] ?? ''}
                      onChange={e => setFieldValues(prev => ({ ...prev, [f.id]: e.target.value }))}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <p style={{ color: 'var(--color-text-subtle)', padding: '24px 0', textAlign: 'center' }}>
                No fields were extracted. The documents may be unsupported or unreadable.
              </p>
            )}

            {/* Attached documents summary */}
            {uploadedFiles.length > 0 && (
              <div className="attached-docs-card">
                <div className="attached-docs-info">
                  <div className="docs-icon" aria-hidden="true"><DocsIcon /></div>
                  <div>
                    <div className="docs-title">Attached Documents</div>
                    <div className="docs-sub">{uploadedFiles.join(' · ')}</div>
                  </div>
                </div>
                <span className="docs-pill">{uploadedFiles.length} File{uploadedFiles.length > 1 ? 's' : ''} Verified</span>
              </div>
            )}

          </div>

          <div className="action-bar" style={{ marginTop: 32 }}>
            <button
              type="button"
              className="btn btn-primary"
              id="validate-btn"
              disabled={loading || fieldDefs.length === 0}
              onClick={handleSubmit}
              aria-label="Validate and submit customer to Business Central"
            >
              {loading && <span className="btn-spinner" aria-hidden="true" />}
              <span>Validate &amp; Submit →</span>
            </button>
          </div>

        </main>
      </div>
    </>
  )
}
