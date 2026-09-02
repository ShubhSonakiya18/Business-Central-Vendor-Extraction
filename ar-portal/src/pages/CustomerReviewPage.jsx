import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import NavBar from '../components/NavBar'
import Stepper from '../components/Stepper'
import './CustomerReviewPage.css'

const CUSTOMER_STEPS = [{ label: 'Upload' }, { label: 'Review' }, { label: 'Submit' }]

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

/**
 * Normalises response from either /onboarding/extract or /extract into a
 * consistent customer dictionary.
 */
function extractCustomerValues(result) {
  if (!result) return {}

  // Direct schema from /onboarding/extract
  if (result.company_name !== undefined || result.billing_address !== undefined) {
    return {
      company_name:            result.company_name ?? '',
      contact_name:            result.contact_name ?? '',
      billing_address:         result.billing_address ?? '',
      city:                    result.city ?? '',
      state:                   result.state ?? '',
      zip_code:                result.zip_code ?? '',
      country:                 result.country ?? '',
      gst_registration_number: result.gst_registration_number ?? '',
      pan_number:              result.pan_number ?? '',
      email_id_to:             result.email_id_to ?? '',
      email_id_cc:             result.email_id_cc ?? '',
      phone_number:            result.phone_number ?? '',
      payment_terms:           result.payment_terms ?? '',
      salesperson:             result.salesperson ?? '',
      region:                  result.region ?? '',
      customer_agreement:      result.customer_agreement ?? '',
      type:                    result.type || 'Services',
    }
  }

  // Schema from standard /extract
  const vals = result.values || {}
  const fields = result.fields || {}
  const getVal = key => vals[key] || fields[key]?.value || ''

  return {
    company_name:            getVal('vendor_name') || getVal('company_name'),
    contact_name:            getVal('contact_name'),
    billing_address:         [getVal('address_1'), getVal('address_2'), getVal('address_3')].filter(Boolean).join(', ') || getVal('billing_address'),
    city:                    getVal('city'),
    state:                   getVal('state'),
    zip_code:                getVal('pin_code') || getVal('zip_code'),
    country:                 getVal('country'),
    gst_registration_number: getVal('gst_number') || getVal('gst_registration_number'),
    pan_number:              getVal('pan') || getVal('pan_number'),
    email_id_to:             getVal('email') || getVal('email_id_to'),
    email_id_cc:             getVal('email_id_cc'),
    phone_number:            getVal('telephone') || getVal('phone_number'),
    payment_terms:           getVal('payment_terms'),
    salesperson:             getVal('salesperson'),
    region:                  getVal('region'),
    customer_agreement:      getVal('customer_agreement'),
    type:                    getVal('type') || 'Services',
  }
}

export default function CustomerReviewPage() {
  const navigate  = useNavigate()
  const location  = useLocation()
  const [loading, setLoading] = useState(false)

  const result = location.state?.result
  const [formData, setFormData] = useState(() => extractCustomerValues(result))

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

  const sourceDocs = result.source_documents?.map(d => d.file_name) ||
                     (Array.isArray(result.documents) ? result.documents.map(d => typeof d === 'string' ? d : d.document) : [])

  function handleChange(field, value) {
    setFormData(prev => ({ ...prev, [field]: value }))
  }

  function handleSubmit() {
    setLoading(true)
    setTimeout(() => navigate('/customer/confirm', { state: { result: { ...result, customerData: formData } } }), 800)
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

              {/* 1. Company Name */}
              <div className="form-group">
                <label className="field-label" htmlFor="company_name">Company Name</label>
                <input
                  id="company_name"
                  type="text"
                  className="form-input"
                  value={formData.company_name}
                  onChange={e => handleChange('company_name', e.target.value)}
                />
              </div>

              {/* 2. Contact Name */}
              <div className="form-group">
                <label className="field-label" htmlFor="contact_name">Contact Name</label>
                <input
                  id="contact_name"
                  type="text"
                  className="form-input"
                  value={formData.contact_name}
                  onChange={e => handleChange('contact_name', e.target.value)}
                />
              </div>

              {/* 3. Billing Address */}
              <div className="form-group field-span-full">
                <label className="field-label" htmlFor="billing_address">Billing Address</label>
                <input
                  id="billing_address"
                  type="text"
                  className="form-input"
                  value={formData.billing_address}
                  onChange={e => handleChange('billing_address', e.target.value)}
                />
              </div>

              {/* 4. City */}
              <div className="form-group">
                <label className="field-label" htmlFor="city">City</label>
                <input
                  id="city"
                  type="text"
                  className="form-input"
                  value={formData.city}
                  onChange={e => handleChange('city', e.target.value)}
                />
              </div>

              {/* 5. State */}
              <div className="form-group">
                <label className="field-label" htmlFor="state">State</label>
                <input
                  id="state"
                  type="text"
                  className="form-input"
                  value={formData.state}
                  onChange={e => handleChange('state', e.target.value)}
                />
              </div>

              {/* 6. Zip code/Pin code */}
              <div className="form-group">
                <label className="field-label" htmlFor="zip_code">Zip code / Pin code</label>
                <input
                  id="zip_code"
                  type="text"
                  className="form-input"
                  value={formData.zip_code}
                  onChange={e => handleChange('zip_code', e.target.value)}
                />
              </div>

              {/* 7. Country */}
              <div className="form-group">
                <label className="field-label" htmlFor="country">Country</label>
                <input
                  id="country"
                  type="text"
                  className="form-input"
                  value={formData.country}
                  onChange={e => handleChange('country', e.target.value)}
                />
              </div>

              {/* 8. GST(ABN,TRN) Registration Certificate */}
              <div className="form-group">
                <label className="field-label" htmlFor="gst_registration_number">GST(ABN,TRN) Registration Certificate</label>
                <input
                  id="gst_registration_number"
                  type="text"
                  className="form-input"
                  value={formData.gst_registration_number}
                  onChange={e => handleChange('gst_registration_number', e.target.value)}
                />
              </div>

              {/* 9. PAN Card (Company/Individual) */}
              <div className="form-group">
                <label className="field-label" htmlFor="pan_number">PAN Card (Company/Individual)</label>
                <input
                  id="pan_number"
                  type="text"
                  className="form-input"
                  value={formData.pan_number}
                  onChange={e => handleChange('pan_number', e.target.value)}
                />
              </div>

              {/* 10. Email ID TO */}
              <div className="form-group">
                <label className="field-label" htmlFor="email_id_to">Email ID TO</label>
                <input
                  id="email_id_to"
                  type="email"
                  className="form-input"
                  value={formData.email_id_to}
                  onChange={e => handleChange('email_id_to', e.target.value)}
                />
              </div>

              {/* 11. Email ID CC */}
              <div className="form-group">
                <label className="field-label" htmlFor="email_id_cc">Email ID CC</label>
                <input
                  id="email_id_cc"
                  type="email"
                  className="form-input"
                  value={formData.email_id_cc}
                  onChange={e => handleChange('email_id_cc', e.target.value)}
                />
              </div>

              {/* 12. Phone Number */}
              <div className="form-group">
                <label className="field-label" htmlFor="phone_number">Phone Number</label>
                <input
                  id="phone_number"
                  type="text"
                  className="form-input"
                  value={formData.phone_number}
                  onChange={e => handleChange('phone_number', e.target.value)}
                />
              </div>

              {/* 13. Payment Terms */}
              <div className="form-group">
                <label className="field-label" htmlFor="payment_terms">Payment Terms</label>
                <input
                  id="payment_terms"
                  type="text"
                  className="form-input"
                  value={formData.payment_terms}
                  onChange={e => handleChange('payment_terms', e.target.value)}
                />
              </div>

              {/* 14. SALESPERSON */}
              <div className="form-group">
                <label className="field-label" htmlFor="salesperson">SALESPERSON</label>
                <input
                  id="salesperson"
                  type="text"
                  className="form-input"
                  value={formData.salesperson}
                  onChange={e => handleChange('salesperson', e.target.value)}
                />
              </div>

              {/* 15. REGION */}
              <div className="form-group">
                <label className="field-label" htmlFor="region">REGION</label>
                <input
                  id="region"
                  type="text"
                  className="form-input"
                  value={formData.region}
                  onChange={e => handleChange('region', e.target.value)}
                />
              </div>

              {/* 16. Customer Agreement / Contract / PO / SO */}
              <div className="form-group field-span-full">
                <label className="field-label" htmlFor="customer_agreement">Customer Agreement / Contract / Purchase Order / Sale Order</label>
                <input
                  id="customer_agreement"
                  type="text"
                  className="form-input"
                  value={formData.customer_agreement}
                  onChange={e => handleChange('customer_agreement', e.target.value)}
                />
              </div>

              {/* 17. Type Dropdown */}
              <div className="form-group">
                <label className="field-label" htmlFor="type">Type</label>
                <select
                  id="type"
                  className="form-input"
                  style={{ cursor: 'pointer', background: 'var(--color-surface)' }}
                  value={formData.type}
                  onChange={e => handleChange('type', e.target.value)}
                >
                  <option value="Services">Services</option>
                  <option value="License">License</option>
                </select>
              </div>

            </div>

            {/* 18. Documents Required & Attached Section */}
            {sourceDocs.length > 0 && (
              <div className="attached-docs-card">
                <div className="attached-docs-info">
                  <div className="docs-icon" aria-hidden="true"><DocsIcon /></div>
                  <div>
                    <div className="docs-title">Documents Required &amp; Attached</div>
                    <div className="docs-sub">{sourceDocs.join(' · ')}</div>
                  </div>
                </div>
                <span className="docs-pill">{sourceDocs.length} Document{sourceDocs.length > 1 ? 's' : ''} Verified</span>
              </div>
            )}

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
