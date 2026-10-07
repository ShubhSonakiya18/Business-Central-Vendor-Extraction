import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import NavBar from '../components/NavBar'
import FileDropzone from '../components/FileDropzone'
import { validateCustomerExcel } from '../api'
import './VendorComparePage.css'
import './CustomerExcelValidationPage.css'

// Read-only review flow: upload a filled Customer Detail Excel, check its GSTIN
// against the live GST registry, and show the Excel values next to the
// registry values. Nothing is saved and no customer is created -- see
// backend/app/services/customer_excel_validation.py.

const STATUS_META = {
  MATCH:                      { label: 'Match',          cls: 'badge--success', issue: false },
  REVIEW:                     { label: 'Review',         cls: 'badge--warning', issue: true  },
  MISMATCH:                   { label: 'Mismatch',       cls: 'badge--danger',  issue: true  },
  NOT_PRESENT_IN_EXCEL:       { label: 'Not in Excel',   cls: 'badge--warning', issue: true  },
  NOT_VALIDATED:              { label: 'Not validated',  cls: 'badge--neutral', issue: false },
  NOT_AVAILABLE_FROM_GST_API: { label: 'Not in GST API', cls: 'badge--neutral', issue: false },
}
const SUMMARY_ORDER = ['MATCH', 'REVIEW', 'MISMATCH', 'NOT_PRESENT_IN_EXCEL', 'NOT_VALIDATED', 'NOT_AVAILABLE_FROM_GST_API']

const PROVIDER_LABEL = { decentro: 'Decentro (GSTIN_DETAILED)', gstinapi: 'gstinapi.in (fallback)' }

function GstPanel({ gst }) {
  const reg = gst.registry || {}
  let tone, headline
  if (!gst.attempted)            { tone = 'warning'; headline = `GST check not run — ${gst.error}` }
  else if (!gst.checked)         { tone = 'danger';  headline = `GST verification failed — ${gst.error}` }
  else if (!gst.record_found)    { tone = 'danger';  headline = 'GSTIN not found in the GST registry' }
  else if (!gst.active)          { tone = 'warning'; headline = `GSTIN is registered but not active (${gst.status || 'unknown status'})` }
  else                           { tone = 'success'; headline = 'GSTIN verified — registration is Active' }

  const facts = [
    ['Provider', PROVIDER_LABEL[gst.provider] || gst.provider || '—'],
    ['GST status', gst.status || '—'],
    ['Legal name', reg.legal_name],
    ['Trade name', reg.trade_name],
    ['Constitution', reg.constitution_of_business],
    ['Taxpayer type', reg.taxpayer_type],
    ['Registration date', reg.registration_date],
    ['Principal place of business', reg.address],
    ['Nature of business', Array.isArray(reg.nature_of_business) ? reg.nature_of_business.join(', ') : ''],
  ].filter(([, v]) => v)

  return (
    <section className={`gst-panel gst-panel--${tone}`} aria-label="GST verification">
      <p className="gst-panel-headline">{headline}</p>
      {gst.provider === 'gstinapi' && gst.primary_error && (
        <p className="gst-panel-fallback" role="note">
          Checked via the fallback provider because Decentro did not answer ({gst.primary_error}).
          Some registry fields (PAN, state, constitution) are not available from the fallback.
        </p>
      )}
      {facts.length > 0 && (
        <dl className="gst-panel-facts">
          {facts.map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      )}
    </section>
  )
}

export default function CustomerExcelValidationPage() {
  const navigate = useNavigate()
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [issuesOnly, setIssuesOnly] = useState(false)

  const file = files[0] || null
  // One workbook at a time: keep only the most recently added file.
  const setSingleFile = updater =>
    setFiles(prev => (typeof updater === 'function' ? updater(prev) : updater).slice(-1))

  async function handleValidate() {
    if (!file) return
    setLoading(true)
    setError('')
    setResult(null)
    try {
      setResult(await validateCustomerExcel(file.fileObject))
    } catch (err) {
      if (err.code === 'AUTH_EXPIRED') { navigate('/'); return }
      setError(err.message || 'Validation failed. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }

  const rows = result
    ? result.validations.filter(r => !issuesOnly || STATUS_META[r.status]?.issue)
    : []

  return (
    <>
      <NavBar />
      <div className="page-wrapper">
        <main className="page-content">

          <a className="back-link" onClick={() => navigate('/dashboard')} style={{ cursor: 'pointer' }}>
            ‹ Dashboard
          </a>

          <h1 className="page-title">Customer Excel Validation</h1>
          <p className="helper-text" style={{ marginBottom: 16 }}>
            Upload a filled <strong>Customer Detail</strong> Excel (.xlsx). Its GSTIN is checked against the
            live GST registry and the details are compared field by field. This is a review only —
            nothing is saved and no customer is created.
          </p>

          {error && <div className="cev-error" role="alert">⚠ {error}</div>}

          <FileDropzone
            files={files}
            setFiles={setSingleFile}
            accept=".xlsx,.xlsm"
          />

          <div className="action-bar">
            <div className="action-bar-inner">
              <span className={`action-hint${file ? ' ready' : ''}`} aria-live="polite">
                {file ? `${file.name} ready — click to validate.` : 'Upload one filled Excel file to continue.'}
              </span>
              <button
                type="button"
                className="btn btn-primary"
                disabled={!file || loading}
                onClick={handleValidate}
              >
                {loading && <span className="btn-spinner" aria-hidden="true" />}
                <span>{loading ? 'Validating…' : 'Validate →'}</span>
              </button>
            </div>
          </div>

          {result && (
            <>
              <GstPanel gst={result.gst_verification} />

              <div className="cev-summary" aria-label="Validation summary">
                {SUMMARY_ORDER.filter(s => result.summary[s]).map(s => (
                  <span key={s} className={`badge ${STATUS_META[s].cls}`}>
                    {STATUS_META[s].label}: {result.summary[s]}
                  </span>
                ))}
                <label className="cev-filter">
                  <input type="checkbox" checked={issuesOnly} onChange={e => setIssuesOnly(e.target.checked)} />
                  Show issues only
                </label>
              </div>

              <div className="table-wrapper" role="region" aria-label="Excel vs GST registry" tabIndex={0}>
                <table className="compare-table">
                  <caption className="sr-only">Customer Excel values compared with the GST registry</caption>
                  <thead>
                    <tr>
                      <th scope="col">Field</th>
                      <th scope="col">Excel Value</th>
                      <th scope="col">GST Registry Value</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(row => {
                      const meta = STATUS_META[row.status] || STATUS_META.NOT_VALIDATED
                      const bad = row.status === 'MISMATCH'
                      return (
                        <tr key={`${row.field}-${row.row}`} className={bad ? 'row-mismatch' : ''}>
                          <td>
                            {row.label}
                            {row.detail && (
                              <div className="field-notes">
                                <div className={`field-note${meta.issue ? ' field-note--warning' : ''}`}>{row.detail}</div>
                              </div>
                            )}
                          </td>
                          <td className={bad ? 'val-mismatch' : ''}>
                            {row.excel_value || <span className="val-absent">Empty</span>}
                          </td>
                          <td>
                            {row.verified_value || <span className="val-absent">—</span>}
                          </td>
                          <td><span className={`badge ${meta.cls}`}>{meta.label}</span></td>
                        </tr>
                      )
                    })}
                    {rows.length === 0 && (
                      <tr>
                        <td colSpan={4} style={{ textAlign: 'center', color: 'var(--color-text-subtle)', padding: '28px 0' }}>
                          No issues found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}

        </main>
      </div>
    </>
  )
}
