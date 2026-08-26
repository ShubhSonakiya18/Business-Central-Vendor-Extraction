import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import NavBar from '../components/NavBar'
import Stepper from '../components/Stepper'
import FileDropzone from '../components/FileDropzone'

const CUSTOMER_STEPS = [
  { label: 'Upload' },
  { label: 'Review' },
  { label: 'Submit' },
]

export default function CustomerUploadPage() {
  const navigate  = useNavigate()
  const [files,   setFiles]   = useState([])
  const [loading, setLoading] = useState(false)

  const ready = files.length > 0

  function handleExtract() {
    if (!ready) return
    setLoading(true)
    setTimeout(() => navigate('/customer/review'), 1200)
  }

  return (
    <>
      <NavBar />
      <div className="page-wrapper">
        <main className="page-content">

          <a className="back-link" onClick={() => navigate('/dashboard')} style={{ cursor: 'pointer' }}>
            ‹ Dashboard
          </a>

          <h1 className="page-title">Customer Creation</h1>
          <Stepper steps={CUSTOMER_STEPS} currentStep={0} />

          <FileDropzone
            files={files}
            setFiles={setFiles}
            accept=".pdf,.xlsx,.xls,.doc,.docx,.png,.jpg,.jpeg"
          />

          <p className="helper-text" style={{ marginTop: 16 }}>
            Upload the customer document — supporting documents (<strong>GST certificate</strong>,{' '}
            <strong>bank letter</strong>, <strong>board resolution</strong>) can all be added here too.
          </p>

          <div className="action-bar">
            <div className="action-bar-inner">
              <span
                className={`action-hint${ready ? ' ready' : ''}`}
                aria-live="polite"
              >
                {ready
                  ? `${files.length} file${files.length > 1 ? 's' : ''} ready — click to extract fields.`
                  : 'Upload at least one file to continue.'}
              </span>
              <button
                type="button"
                className="btn btn-primary"
                id="extract-btn"
                disabled={!ready || loading}
                onClick={handleExtract}
                aria-label="Extract fields from uploaded documents"
              >
                {loading && <span className="btn-spinner" aria-hidden="true" />}
                <span>Extract Fields →</span>
              </button>
            </div>
          </div>

        </main>
      </div>
    </>
  )
}
