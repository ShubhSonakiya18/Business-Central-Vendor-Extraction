import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import NavBar from '../components/NavBar'
import Stepper from '../components/Stepper'
import { downloadFile } from '../api'
import './VendorComparePage.css'

const VENDOR_STEPS = [{ label: 'Upload' }, { label: 'Compare' }, { label: 'Submit' }]

const WarnIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round">
    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
    <line x1="12" y1="9"  x2="12"   y2="13"/>
    <line x1="12" y1="17" x2="12.01" y2="17"/>
  </svg>
)

const DownloadIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" width="15" height="15">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
    <polyline points="7 10 12 15 17 10"/>
    <line x1="12" y1="15" x2="12" y2="3"/>
  </svg>
)

/**
 * Normalise the backend `fields` map into rows the comparison table can render.
 *
 * The backend shape per field (see backend/app/services/extraction_pipeline/
 * models.py FieldResult.to_dict, extended in routers/extraction.py
 * _run_as_json):
 *   { value, confidence, notes, ...,
 *     excel_value: string|null,     -- only present when excelUploaded
 *     excel_mismatch: boolean }     -- true only when BOTH sides have a
 *                                      value and they disagree
 *
 * "Extracted Value" is always what OCR read off the uploaded PDF/DOCX/image
 * documents. "Excel / Template Value" is exactly what the vendor filled into
 * the uploaded Excel form's matching cell -- read BEFORE that cell gets
 * overwritten with the extracted value while building the filled workbook
 * (see extraction.py fill_and_verify) -- so the two columns are genuinely
 * independent sources, not the same value shown twice.
 *
 * needs_review: string[] — field names the extraction pipeline itself
 * flagged (low OCR confidence, failed validation, etc). This is separate
 * from an excel_mismatch and both can fire independently on the same row.
 */
function buildRows(fields, needsReview, excelUploaded) {
  const reviewSet = new Set(needsReview ?? [])

  return Object.entries(fields).map(([label, field]) => {
    const pdfValue = field.value ?? ''
    // No Excel was uploaded for this run at all -- there is nothing to
    // compare, not merely a missing value, so the column reads
    // "Not in template" rather than a false mismatch/blank.
    const isSingle = !excelUploaded

    const excelValue     = isSingle ? null : (field.excel_value ?? '')
    const excelMismatch  = !isSingle && Boolean(field.excel_mismatch)
    const needsReviewFlag = reviewSet.has(label)
    const isMismatch     = excelMismatch || needsReviewFlag

    return {
      label, pdfValue, excelValue, isSingle,
      excelMismatch, needsReviewFlag, isMismatch,
      confidence: field.confidence,
    }
  })
}

export default function VendorComparePage() {
  const navigate      = useNavigate()
  const location      = useLocation()
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')

  // Receive the extraction result that VendorUploadPage passed via navigation state
  const result = location.state?.result

  // If user lands here directly without going through upload, redirect back
  if (!result) {
    return (
      <>
        <NavBar />
        <div className="page-wrapper">
          <main className="page-content">
            <p style={{ color: 'var(--color-text-muted)', marginTop: 40 }}>
              No extraction data found.{' '}
              <a className="back-link" onClick={() => navigate('/vendor/upload')} style={{ cursor: 'pointer', display: 'inline' }}>
                Go back to Upload
              </a>
            </p>
          </main>
        </div>
      </>
    )
  }

  const excelUploaded = Boolean(result.excel_uploaded)
  const rows          = buildRows(result.fields ?? {}, result.needs_review ?? [], excelUploaded)
  const mismatchCount = rows.filter(r => r.isMismatch).length
  const hasXlsx       = result.files?.includes('xlsx')

  function handleSubmit() {
    setLoading(true)
    setTimeout(() => navigate('/vendor/confirm', { state: { result } }), 800)
  }

  async function handleDownloadXlsx() {
    setDownloadError('')
    setDownloading(true)
    try {
      const vendor = (result.fields?.vendor_name?.value || 'vendor')
        .replace(/[^\w.-]+/g, '_')
      await downloadFile(result.run_id, 'xlsx', `${vendor}-filled.xlsx`)
    } catch (err) {
      if (err.code === 'AUTH_EXPIRED') { navigate('/login'); return }
      setDownloadError(err.message || 'Download failed. Please try again.')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <>
      <NavBar />
      <div className="page-wrapper">
        <main className="page-content">

          <a className="back-link" onClick={() => navigate('/vendor/upload')} style={{ cursor: 'pointer' }}>
            ‹ Upload
          </a>

          <h1 className="page-title">Vendor Creation</h1>

          {/* Timing pill */}
          {result.timings && (
            <p style={{ fontSize: '0.8rem', color: 'var(--color-text-subtle)', marginBottom: 4 }}>
              Extracted {result.summary?.filled ?? 0}/{result.summary?.total_fields ?? 0} fields
              in {result.timings.total}s
            </p>
          )}

          <Stepper steps={VENDOR_STEPS} currentStep={1} />

          <div className="table-wrapper" role="region" aria-label="Vendor data comparison" tabIndex={0}>
            <table className="compare-table">
              <caption className="sr-only">
                Extracted vendor fields — review before submitting to Business Central
              </caption>
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Extracted Value</th>
                  <th scope="col">Excel / Template Value</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(row => (
                  <tr key={row.label} className={row.isMismatch ? 'row-mismatch' : ''}>
                    <td>{row.label}</td>
                    <td className={row.excelMismatch ? 'val-mismatch' : ''}>{row.pdfValue}</td>
                    <td>
                      {row.isSingle
                        ? <span className="val-absent">Not in template</span>
                        : (row.excelValue
                            ? <span className={row.excelMismatch ? 'val-mismatch' : ''}>{row.excelValue}</span>
                            : <span className="val-absent">Not filled in Excel</span>)}
                    </td>
                    <td>
                      {row.isSingle && <span className="badge badge--neutral">Single source</span>}
                      {row.excelMismatch && <span className="badge badge--warning">PDF ≠ Excel</span>}
                      {!row.excelMismatch && row.needsReviewFlag && <span className="badge badge--warning">Review</span>}
                      {!row.isSingle && !row.isMismatch && <span className="badge badge--success">Match</span>}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={4} style={{ textAlign: 'center', color: 'var(--color-text-subtle)', padding: '28px 0' }}>
                      No fields extracted. Try uploading clearer documents.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="action-bar">
            <div className="action-bar-inner">

              {/* Download filled Excel if available. Goes through fetch() (see
                  api.downloadFile) so the request carries the auth token and
                  the ngrok-skip-browser-warning header -- a plain <a href>
                  navigation would hit ngrok's interstitial page instead. */}
              {hasXlsx && (
                <button
                  type="button"
                  onClick={handleDownloadXlsx}
                  disabled={downloading}
                  className="btn btn-outline"
                  style={{ marginRight: 8 }}
                >
                  <DownloadIcon /> {downloading ? 'Preparing…' : 'Download filled Excel'}
                </button>
              )}
              {downloadError && (
                <div className="mismatch-warning" aria-live="polite" style={{ marginRight: 8 }}>
                  <WarnIcon /> {downloadError}
                </div>
              )}

              {mismatchCount > 0 && (
                <div className="mismatch-warning" aria-live="polite">
                  <WarnIcon /> {mismatchCount} field{mismatchCount > 1 ? 's' : ''} flagged for review — check before submitting.
                </div>
              )}

              <button
                type="button"
                className="btn btn-primary"
                id="submit-btn"
                disabled={loading}
                onClick={handleSubmit}
                aria-label="Validate and submit vendor data to Business Central"
              >
                {loading && <span className="btn-spinner" aria-hidden="true" />}
                <span>Validate &amp; Submit →</span>
              </button>

            </div>
          </div>

        </main>
      </div>
    </>
  )
}
