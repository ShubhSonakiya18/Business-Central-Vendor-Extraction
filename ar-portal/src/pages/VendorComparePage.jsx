import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import NavBar from '../components/NavBar'
import Stepper from '../components/Stepper'
import './VendorComparePage.css'

const VENDOR_STEPS = [{ label: 'Upload' }, { label: 'Compare' }, { label: 'Submit' }]

const FIELDS = [
  { label: 'Vendor Name',                        pdf: 'Rajesh Enterprises Pvt Ltd',   excel: 'Rajesh Enterprises Pvt Ltd' },
  { label: 'Address 1',                          pdf: '42, Industrial Estate',         excel: '42, Industrial Estate' },
  { label: 'Address 2',                          pdf: 'Sector 18',                     excel: 'Sector 18' },
  { label: 'Address 3',                          pdf: 'MIDC Area',                     excel: 'MIDC Area' },
  { label: 'Address 4',                          pdf: 'Near Highway 48',               excel: null },
  { label: 'City',                               pdf: 'Pune',                          excel: 'Pune' },
  { label: 'State',                              pdf: 'Maharashtra',                   excel: 'Maharashtra' },
  { label: 'Country',                            pdf: 'India',                         excel: 'India' },
  { label: 'Pin Code',                           pdf: '411018',                        excel: '411018' },
  { label: 'Telephone 1',                        pdf: '+91-20-27404521',               excel: '+91-20-27404521' },
  { label: 'Telephone 2',                        pdf: '+91-9876543210',                excel: '+91-9876543210' },
  { label: 'E-mail ID',                          pdf: 'accounts@rajeshent.com',        excel: 'accounts@rajeshent.com' },
  { label: 'Website',                            pdf: 'www.rajeshenterprises.in',      excel: 'www.rajeshenterprises.in' },
  { label: 'Company / Non-Company',              pdf: 'Company',                       excel: 'Company' },
  { label: 'Nature of Business',                 pdf: 'Manufacturing',                 excel: 'Manufacturing' },
  { label: 'TAN No.',                            pdf: 'PNRJ12345F',                    excel: 'PNRJ12345F' },
  { label: 'PAN',                                pdf: 'AABCR1234L',                    excel: 'AABCR1234M',  mismatch: true },
  { label: 'TDS Section / Condition Applicable', pdf: '194C',                          excel: '194C' },
  { label: 'GST No.',                            pdf: '27AABCR1234L1ZD',               excel: '27AABCR1234L1ZS', mismatch: true },
  { label: 'ESIC No.',                           pdf: '31000343210001234',             excel: '31000343210001234' },
  { label: 'MSME Vendor (UAN No. if applicable)',pdf: 'Yes – MH18D0000001',            excel: 'Yes – MH18D0000001' },
  { label: 'Bank Name',                          pdf: 'HDFC Bank Ltd',                 excel: 'HDFC Bank Ltd' },
  { label: 'Branch Address',                     pdf: 'FC Road Branch, Pune',          excel: 'FC Road Branch, Pune' },
  { label: 'IFSC / SWIFT Code',                  pdf: 'HDFC0001234',                   excel: 'HDFC0001234' },
  { label: 'Account Type (CA/CC/SB)',            pdf: 'CA',                            excel: 'CA' },
  { label: 'Account Number',                     pdf: '50100234567890',                excel: '50100234567891', mismatch: true },
]

const WarnIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round">
    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
    <line x1="12" y1="9"  x2="12"   y2="13"/>
    <line x1="12" y1="17" x2="12.01" y2="17"/>
  </svg>
)

export default function VendorComparePage() {
  const navigate   = useNavigate()
  const [loading,  setLoading] = useState(false)
  const mismatchCount = FIELDS.filter(f => f.excel !== null && f.mismatch).length

  function handleSubmit() {
    setLoading(true)
    setTimeout(() => navigate('/vendor/confirm'), 1000)
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
          <Stepper steps={VENDOR_STEPS} currentStep={1} />

          <div className="table-wrapper" role="region" aria-label="Vendor data comparison" tabIndex={0}>
            <table className="compare-table">
              <caption className="sr-only">
                Comparison of vendor fields extracted from the PDF and Excel files
              </caption>
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">PDF Value</th>
                  <th scope="col">Excel Value</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {FIELDS.map(row => {
                  const isSingle   = row.excel === null
                  const isMismatch = !isSingle && row.mismatch === true
                  return (
                    <tr key={row.label} className={isMismatch ? 'row-mismatch' : ''}>
                      <td>{row.label}</td>
                      <td className={isMismatch ? 'val-mismatch' : ''}>{row.pdf}</td>
                      <td>
                        {isSingle
                          ? <span className="val-absent">Not present in Excel</span>
                          : <span className={isMismatch ? 'val-mismatch' : ''}>{row.excel}</span>}
                      </td>
                      <td>
                        {isSingle   && <span className="badge badge--neutral">Single source</span>}
                        {isMismatch && <span className="badge badge--warning">Mismatch</span>}
                        {!isSingle && !isMismatch && <span className="badge badge--success">Match</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="action-bar">
            <div className="action-bar-inner">
              {mismatchCount > 0 && (
                <div className="mismatch-warning" aria-live="polite">
                  <WarnIcon /> Resolve all mismatches before submitting.
                </div>
              )}
              <button
                type="button"
                className="btn btn-primary"
                id="submit-btn"
                disabled={mismatchCount > 0 || loading}
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
