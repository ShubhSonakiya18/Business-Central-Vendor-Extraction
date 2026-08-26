import { useNavigate } from 'react-router-dom'
import NavBar from '../components/NavBar'
import Stepper from '../components/Stepper'
import './ConfirmPage.css'

const CUSTOMER_STEPS = [{ label: 'Upload' }, { label: 'Review' }, { label: 'Submit' }]

const CheckIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20,6 9,17 4,12"/>
  </svg>
)

export default function CustomerConfirmPage() {
  const navigate = useNavigate()
  return (
    <>
      <NavBar />
      <div className="page-wrapper">
        <main className="page-content">
          <Stepper steps={CUSTOMER_STEPS} currentStep={3} />

          <div className="success-wrap fade-up">
            <div className="success-icon-outer">
              <div className="success-icon"><CheckIcon /></div>
            </div>

            <h1 className="success-heading">Customer created successfully</h1>

            <p className="success-sub">
              <strong>Apex Global Logistics Pvt Ltd</strong> has been added to Business Central
              and is ready for use.
            </p>

            <div className="btn-group" role="group" aria-label="Next steps">
              <button className="btn btn-secondary" id="create-another-btn"
                      onClick={() => navigate('/customer/upload')}>
                Create another customer
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
