import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import NavBar from '../components/NavBar'
import Stepper from '../components/Stepper'
import FileDropzone from '../components/FileDropzone'
import { extractDocuments } from '../api'

const VENDOR_STEPS = [
  { label: 'Upload' },
  { label: 'Compare' },
  { label: 'Submit' },
]

export default function VendorUploadPage() {
  const navigate  = useNavigate()
  const [files,   setFiles]   = useState([])
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState('')

  const hasPDF   = files.some(f => f.type === 'pdf')
  const hasExcel = files.some(f => f.type === 'excel')
  const ready    = hasPDF && hasExcel

  let hintText = ''
  if (ready) {
    hintText = 'Ready — click to extract and compare.'
  } else {
    const missing = []
    if (!hasPDF)   missing.push('a PDF')
    if (!hasExcel) missing.push('an Excel file')
    hintText = `Add ${missing.join(' and ')} to continue.`
  }

  async function handleExtract() {
    if (!ready) return
    setLoading(true)
    setError('')

    try {
      // Separate PDFs (source documents) from the Excel template
      const docFiles      = files.filter(f => f.type !== 'excel').map(f => f.fileObject)
      const templateFile  = files.find(f => f.type === 'excel')?.fileObject ?? null

      const result = await extractDocuments(docFiles, templateFile)

      // Pass extraction result forward via React Router location state
      navigate('/vendor/compare', { state: { result } })
    } catch (err) {
      setError(err.message || 'Extraction failed. Is the backend running?')
      setLoading(false)
    }
  }

  return (
    <>
      <NavBar />
      <div className="page-wrapper">
        <main className="page-content">

          <a className="back-link" onClick={() => navigate('/dashboard')} style={{ cursor: 'pointer' }}>
            ‹ Dashboard
          </a>

          <h1 className="page-title">Vendor Creation</h1>
          <Stepper steps={VENDOR_STEPS} currentStep={0} />

          {/* API error banner */}
          {error && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: '#FEF2F2', border: '1px solid #FECACA',
              borderRadius: 10, padding: '11px 14px',
              fontSize: '0.85rem', color: '#991B1B', fontWeight: 500,
              marginBottom: 20,
            }} role="alert">
              ⚠ {error}
            </div>
          )}

          <FileDropzone
            files={files}
            setFiles={setFiles}
            accept=".pdf,.xlsx,.xls,.doc,.docx,.csv"
          />

          <p className="helper-text" style={{ marginTop: 16 }}>
            Upload the Vendor Registration Form as a <strong>PDF</strong> and the supporting{' '}
            <strong>Excel</strong> sheet — additional supporting documents can be added too.
          </p>

          <div className="action-bar">
            <div className="action-bar-inner">
              <span className={`action-hint${ready ? ' ready' : ''}`} aria-live="polite">
                {hintText}
              </span>
              <button
                type="button"
                className="btn btn-primary"
                id="extract-btn"
                disabled={!ready || loading}
                onClick={handleExtract}
                aria-label="Extract and compare vendor data from uploaded files"
              >
                {loading && <span className="btn-spinner" aria-hidden="true" />}
                <span>{loading ? 'Extracting…' : 'Extract & Compare →'}</span>
              </button>
            </div>
          </div>

        </main>
      </div>
    </>
  )
}
