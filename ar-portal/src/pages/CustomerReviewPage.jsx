import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import NavBar from '../components/NavBar'
import Stepper from '../components/Stepper'
import './CustomerReviewPage.css'

const CUSTOMER_STEPS = [{ label: 'Upload' }, { label: 'Review' }, { label: 'Submit' }]

const FIELDS = [
  { id: 'company-name',   label: 'Company Name',                   value: 'Apex Global Logistics Pvt Ltd',        conf: 98,  low: false },
  { id: 'contact-name',  label: 'Contact Name',                    value: 'Vikram Malhotra',                      conf: 95,  low: false },
  { id: 'billing-addr',  label: 'Billing Address',                 value: 'Plot No. 88, Udyog Vihar Phase IV, Cyber City', conf: 92, low: false, fullWidth: true },
  { id: 'city',          label: 'City',                            value: 'Gurugram',                             conf: 99,  low: false },
  { id: 'state',         label: 'State',                           value: 'Haryana',                              conf: 99,  low: false },
  { id: 'zip-code',      label: 'Zip / Pin Code',                  value: '122015',                               conf: 94,  low: false },
  { id: 'country',       label: 'Country',                         value: 'India',                                conf: 100, low: false },
  { id: 'gst-no',        label: 'GST (ABN/TRN) Reg. Cert. No.',   value: '06AAACA4512P1ZV',                       conf: 61,  low: true },
  { id: 'pan-no',        label: 'PAN Card No. (Company/Individual)', value: 'AAACA4512P',                         conf: 89,  low: false },
  { id: 'email-to',      label: 'Email ID TO',                     value: 'billing@apexlogistics.in',             conf: 96,  low: false },
  { id: 'email-cc',      label: 'Email ID CC',                     value: 'v.malhotra@apexlogistics.in',          conf: 91,  low: false },
  { id: 'phone-no',      label: 'Phone Number',                    value: '+91-124-4982100',                      conf: 93,  low: false },
  { id: 'payment-terms', label: 'Payment Terms',                   value: 'Net 30 Days',                          conf: 97,  low: false },
  { id: 'salesperson',   label: 'Salesperson',                     value: 'Amit Sharma (SP-104)',                  conf: 90,  low: false },
  { id: 'region',        label: 'Region',                          value: 'North India / NCR',                    conf: 99,  low: false },
  { id: 'type',          label: 'Type (Services / License)',        value: 'Services & SaaS Subscription',        conf: 95,  low: false, fullWidth: true },
]

const DocsIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
    <polyline points="14 2 14 8 20 8"/>
    <line x1="16" y1="13" x2="8" y2="13"/>
    <line x1="16" y1="17" x2="8" y2="17"/>
    <polyline points="10 9 9 9 8 9"/>
  </svg>
)

export default function CustomerReviewPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [fieldValues, setFieldValues] = useState(
    Object.fromEntries(FIELDS.map(f => [f.id, f.value]))
  )

  function handleSubmit() {
    setLoading(true)
    setTimeout(() => navigate('/customer/confirm'), 1000)
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
          <Stepper steps={CUSTOMER_STEPS} currentStep={1} />

          <div className="review-card" role="region" aria-label="Extracted Customer Fields">
            <div className="fields-grid">
              {FIELDS.map(f => (
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
                    <span className={`conf-badge${f.low ? ' conf-low' : ' conf-high'}`}
                          title={`${f.conf}% confidence`}>
                      {f.conf}% {f.low ? 'review' : 'match'}
                    </span>
                  </div>
                  <input
                    id={f.id}
                    type="text"
                    className={`form-input${f.low ? ' input-low-confidence' : ''}`}
                    value={fieldValues[f.id]}
                    onChange={e => setFieldValues(prev => ({ ...prev, [f.id]: e.target.value }))}
                  />
                </div>
              ))}
            </div>

            {/* Attached docs summary */}
            <div className="attached-docs-card">
              <div className="attached-docs-info">
                <div className="docs-icon"><DocsIcon /></div>
                <div>
                  <div className="docs-title">Attached Customer Agreement &amp; Supporting Documents</div>
                  <div className="docs-sub">
                    Customer_Agreement_Apex_2026.pdf · GST_Registration_Cert.pdf · Board_Resolution_Signed.pdf
                  </div>
                </div>
              </div>
              <span className="docs-pill">3 Files Verified</span>
            </div>
          </div>

          <div className="action-bar" style={{ marginTop: 32 }}>
            <button
              type="button"
              className="btn btn-primary"
              id="validate-btn"
              disabled={loading}
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
