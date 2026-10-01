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

const EditIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
    <path d="M12 20h9"/>
    <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z"/>
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
      userEdited: Boolean(field.user_edited),
      confidence: field.confidence,
      // Extra provenance/annotations a FieldResult may carry -- currently
      // used for the live GSTIN registry check (see
      // extraction.py:_apply_gstin_verification), but generic to any future
      // per-field note. Empty for every field that has none.
      notes: field.notes ?? [],
    }
  })
}

export default function VendorComparePage() {
  const navigate      = useNavigate()
  const location      = useLocation()
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')

  // Local, editable copy of the extraction result passed in via navigation
  // state. A reviewer can correct misread values here before they move on to
  // Confirm/Submit -- nothing is sent back to the backend by this page itself
  // (there is no persistence step between Compare and Confirm today), so an
  // edit just needs to update this in-memory copy, which is what flows
  // forward via navigate(..., { state: { result } }) exactly as the
  // unedited result already did.
  //
  // One global edit toggle rather than a per-row pencil: a reviewer
  // correcting several fields would otherwise have to open/save/reopen each
  // row one at a time. "Edit" puts every row's Extracted Value cell into an
  // input at once, drafted in `draftValues` (label -> string) so nothing is
  // written back to `editedResult` -- and so nothing the Compare table
  // reads -- until "Save changes" commits the whole set in one update.
  // "Cancel" discards the draft instead.
  const [editedResult, setEditedResult] = useState(location.state?.result ?? null)
  const [editMode, setEditMode] = useState(false)
  const [draftValues, setDraftValues] = useState({})

  const result = editedResult

  function startEditAll(fields) {
    const draft = {}
    for (const [label, field] of Object.entries(fields ?? {})) {
      draft[label] = field.value ?? ''
    }
    setDraftValues(draft)
    setEditMode(true)
  }

  function cancelEditAll() {
    setEditMode(false)
    setDraftValues({})
  }

  function saveEditAll() {
    setEditedResult(prev => {
      const nextFields = { ...prev.fields }
      for (const [label, value] of Object.entries(draftValues)) {
        const field = nextFields[label] ?? {}
        const changed = (field.value ?? '') !== value
        nextFields[label] = changed
          ? { ...field, value, user_edited: true }
          : field
      }
      return { ...prev, fields: nextFields }
    })
    setEditMode(false)
    setDraftValues({})
  }

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
                    <td>
                      {row.label}
                      {row.notes.length > 0 && (
                        <div className="field-notes">
                          {row.notes.map((note, i) => {
                            const cls = note.includes('NOT active')
                              ? 'field-note field-note--warning'
                              : note.startsWith('GST registry: active')
                                ? 'field-note field-note--active'
                                : 'field-note'
                            return <div key={i} className={cls}>{note}</div>
                          })}
                        </div>
                      )}
                    </td>
                    <td className={row.excelMismatch ? 'val-mismatch' : ''}>
                      {editMode ? (
                        <input
                          type="text"
                          value={draftValues[row.label] ?? ''}
                          onChange={e => setDraftValues(d => ({ ...d, [row.label]: e.target.value }))}
                          style={{
                            width: '100%', padding: '4px 8px', fontSize: '0.85rem',
                            border: '1px solid var(--color-border, #ccc)', borderRadius: 6,
                          }}
                        />
                      ) : (
                        row.pdfValue
                      )}
                    </td>
                    <td>
                      {row.isSingle
                        ? <span className="val-absent">Not in template</span>
                        : (row.excelValue
                            ? <span className={row.excelMismatch ? 'val-mismatch' : ''}>{row.excelValue}</span>
                            : <span className="val-absent">Not filled in Excel</span>)}
                    </td>
                    <td>
                      {row.userEdited && <span className="badge badge--neutral">Edited</span>}
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

              {/* One global edit toggle for the whole table -- see the
                  editMode/draftValues comment above buildRows usage for why
                  this replaces a per-row pencil. */}
              {editMode ? (
                <>
                  <button type="button" className="btn btn-primary" style={{ marginRight: 8 }}
                          onClick={saveEditAll}>
                    Save changes
                  </button>
                  <button type="button" className="btn btn-outline" style={{ marginRight: 8 }}
                          onClick={cancelEditAll}>
                    Cancel
                  </button>
                </>
              ) : (
                <button type="button" className="btn btn-outline" style={{ marginRight: 8 }}
                        onClick={() => startEditAll(result.fields)}>
                  <EditIcon /> Edit
                </button>
              )}

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
                disabled={loading || editMode}
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
