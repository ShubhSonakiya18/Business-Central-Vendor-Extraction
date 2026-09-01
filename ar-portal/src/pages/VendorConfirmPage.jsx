import { useNavigate, useLocation } from 'react-router-dom'
import NavBar from '../components/NavBar'
import Stepper from '../components/Stepper'
import './ConfirmPage.css'

const VENDOR_STEPS = [{ label: 'Upload' }, { label: 'Compare' }, { label: 'Submit' }]

const CheckIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20,6 9,17 4,12"/>
  </svg>
)

export default function VendorConfirmPage() {
  const navigate = useNavigate()
  const location = useLocation()

  // Passed from VendorComparePage's handleSubmit() via navigate(..., { state }).
  // A direct visit to /vendor/confirm (refresh, bookmark, back-button after
  // history changes) has no state, so fall back to a generic message rather
  // than a name that isn't this visit's vendor.
  const result     = location.state?.result
  const vendorName = result?.fields?.vendor_name?.value

  return (
    <>
      <NavBar />
      <div className="page-wrapper">
        <main className="page-content">
          <Stepper steps={VENDOR_STEPS} currentStep={3} />

          <div className="success-wrap fade-up">
            <div className="success-icon-outer">
              <div className="success-icon"><CheckIcon /></div>
            </div>

            <h1 className="success-heading">Vendor created successfully</h1>

            <p className="success-sub">
              {vendorName
                ? <><strong>{vendorName}</strong> has been added to Business Central and is ready for use.</>
                : 'The vendor has been added to Business Central and is ready for use.'}
            </p>

            <div className="btn-group" role="group" aria-label="Next steps">
              <button className="btn btn-secondary" id="create-another-btn"
                      onClick={() => navigate('/vendor/upload')}>
                Create another vendor
              </button>
              <button className="btn btn-primary" id="dashboard-btn"
                      onClick={() => navigate('/dashboard')}>
                Back to Dashboard
              </button>
            </div>
          </div>
        </main>
      </div>
    </>
  )
}
