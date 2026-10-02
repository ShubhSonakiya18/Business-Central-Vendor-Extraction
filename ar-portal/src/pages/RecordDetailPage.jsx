import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import NavBar from '../components/NavBar'
import {
  getVendorById, getCustomerById, getVendorBcPayload, markVendorPushed,
  getCustomerBcPayload, markCustomerPushed, confirmVendorAddress,
  updateVendor, deleteVendor, updateCustomer, deleteCustomer,
} from '../api'
import './RecordsPage.css'

// Field groups per record kind, in display order. Keys match the *Out schema.
const VENDOR_GROUPS = [
  ['Identity', [
    ['vendor_name', 'Vendor Name'], ['company_type', 'Company / Non-Company'],
    ['nature_of_business', 'Nature of Business'],
  ]],
  ['Address', [
    ['address_1', 'Address 1'], ['address_2', 'Address 2'], ['address_3', 'Address 3'],
    ['address_4', 'Address 4'], ['city', 'City'], ['state', 'State'],
    ['country', 'Country'], ['pin_code', 'Pin Code'],
  ]],
  ['Contact', [
    ['telephone_1', 'Telephone 1'], ['telephone_2', 'Telephone 2'],
    ['email', 'E-mail'], ['website', 'Website'],
  ]],
  ['Statutory', [
    ['pan', 'PAN'], ['gst_no', 'GST No.'], ['tan_no', 'TAN No.'],
    ['esic_no', 'ESIC No.'], ['udyam_no', 'Udyam No.'], ['tds_applicable', 'TDS Applicable'],
  ]],
  ['Bank', [
    ['bank_name', 'Bank Name'], ['branch_address', 'Branch Address'],
    ['ifsc_swift_code', 'IFSC / SWIFT'], ['account_type', 'Account Type'],
    ['account_number', 'Account Number'],
  ]],
]

const CUSTOMER_GROUPS = [
  ['Identity', [
    ['company_name', 'Company Name'], ['contact_name', 'Contact Name'], ['type', 'Type'],
  ]],
  ['Address', [
    ['billing_address', 'Billing Address'], ['city', 'City'], ['state', 'State'],
    ['zip_code', 'Zip / Pin Code'], ['country', 'Country'],
  ]],
  ['Contact', [
    ['email_id_to', 'Email ID TO'], ['email_id_cc', 'Email ID CC'], ['phone_number', 'Phone Number'],
  ]],
  ['Statutory', [
    ['gst_registration_number', 'GST Registration No.'], ['pan_number', 'PAN'],
  ]],
  ['Commercial', [
    ['payment_terms', 'Payment Terms'], ['salesperson', 'Salesperson'],
    ['region', 'Region'], ['customer_agreement', 'Customer Agreement'],
  ]],
]

const CFG = {
  vendor: {
    fetch: getVendorById, update: updateVendor, remove: deleteVendor,
    groups: VENDOR_GROUPS, nameKey: 'vendor_name', title: 'Vendor',
    bcFetch: getVendorBcPayload, bcMark: markVendorPushed,
  },
  customer: {
    fetch: getCustomerById, update: updateCustomer, remove: deleteCustomer,
    groups: CUSTOMER_GROUPS, nameKey: 'company_name', title: 'Customer',
    bcFetch: getCustomerBcPayload, bcMark: markCustomerPushed,
  },
}

// The one required field per kind — cannot be blanked while editing.
const REQUIRED = { vendor: 'vendor_name', customer: 'company_name' }
// customer.type is a fixed choice
const TYPE_OPTIONS = ['Services', 'License']

// Business Central gate findings (docs/ADDRESS_SEGMENTATION_PLAN.md s.7):
// what each reason code means to a reviewer.
const BC_REASON_LABELS = {
  ADDRESS_BC_LENGTH_REBALANCE: 'Address line break moved to fit Business Central',
  ADDRESS_OVERFLOW: "Address does not fit Business Central's two address lines",
  FIELD_TOO_LONG: 'Too long for Business Central',
  INVALID_COUNTRY: 'Country has no Business Central code',
  INVALID_PIN: 'PIN is not a 6-digit Indian PIN',
  ADDRESS_INVARIANT_VIOLATION: 'Address check failed',
}
const BC_FIELD_LABELS = {
  address_1: 'Address', address_2: 'Address 2', address_3: 'Address 3', address_4: 'Address 4',
  city: 'City', state: 'State (County)', pin_code: 'PIN (Post Code)', country: 'Country',
  vendor_name: 'Name', telephone_1: 'Phone', telephone_2: 'Mobile phone',
  email: 'E-mail', website: 'Website (Home Page)',
}

function fmtDate(s) {
  if (!s) return '—'
  const d = new Date(s)
  return isNaN(d) ? s : d.toLocaleString()
}

export default function RecordDetailPage() {
  const navigate = useNavigate()
  const { kind = 'vendor', id } = useParams()
  const cfg = CFG[kind] || CFG.vendor
  const requiredKey = REQUIRED[kind] || REQUIRED.vendor

  const [rec, setRec] = useState(null)
  const [error, setError] = useState('')

  // edit state
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({})
  const [saving, setSaving] = useState(false)
  const [editErr, setEditErr] = useState('')

  // delete state
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)

  // BC manual-push panel state (vendor and customer)
  const [bc, setBc] = useState(null)
  const [bcErr, setBcErr] = useState('')
  const [bcNoInput, setBcNoInput] = useState('')
  const [marking, setMarking] = useState(false)
  // Open findings from the BC payload gate (409), and the one-click confirm
  const [bcFindings, setBcFindings] = useState(null)
  const [confirming, setConfirming] = useState(false)

  const editableKeys = useMemo(
    () => cfg.groups.flatMap(([, fields]) => fields.map(([k]) => k)),
    [cfg],
  )

  function loadRecord() {
    setRec(null); setError('')
    cfg.fetch(id)
      .then(setRec)
      .catch(err => {
        if (err.code === 'AUTH_EXPIRED') { navigate('/', { replace: true }); return }
        setError(err.status === 404 ? 'Record not found.' : (err.message || 'Could not load record.'))
      })
  }

  useEffect(() => {
    loadRecord()
    setEditing(false); setEditErr(''); setConfirmDelete(false)
    setBc(null); setBcErr(''); setBcNoInput('')
  }, [kind, id]) // eslint-disable-line react-hooks/exhaustive-deps

  function startEdit() {
    const seed = {}
    editableKeys.forEach(k => { seed[k] = rec[k] ?? '' })
    setForm(seed)
    setEditErr('')
    setEditing(true)
  }

  function saveEdit() {
    if (!String(form[requiredKey] || '').trim()) {
      setEditErr(`${requiredKey.replace(/_/g, ' ')} cannot be empty.`)
      return
    }
    // send only changed fields
    const changes = {}
    editableKeys.forEach(k => {
      const now = form[k] ?? ''
      const was = rec[k] ?? ''
      if (now !== was) changes[k] = now
    })
    if (Object.keys(changes).length === 0) { setEditing(false); return }

    setSaving(true); setEditErr('')
    cfg.update(id, changes)
      .then(updated => { setSaving(false); setEditing(false); setRec(updated) })
      .catch(err => {
        setSaving(false)
        if (err.code === 'AUTH_EXPIRED') { navigate('/', { replace: true }); return }
        setEditErr(err.status === 409
          ? (err.body?.detail?.message || 'Another record already has this GSTIN.')
          : (err.message || 'Could not save changes.'))
      })
  }

  function doDelete() {
    setDeleting(true)
    cfg.remove(id)
      .then(() => navigate(`/records/${kind}`, { replace: true }))
      .catch(err => {
        setDeleting(false)
        if (err.code === 'AUTH_EXPIRED') { navigate('/', { replace: true }); return }
        setError(err.message || 'Could not delete this record.')
        setConfirmDelete(false)
      })
  }

  function fetchBcPayload() {
    setBcErr('')
    setBcFindings(null)
    cfg.bcFetch(id)
      .then(setBc)
      .catch(err => {
        if (err.code === 'AUTH_EXPIRED') { navigate('/', { replace: true }); return }
        const findings = err.body?.detail?.findings
        if (err.status === 409 && Array.isArray(findings)) {
          // The record is not ready for BC yet: show what must be fixed.
          setBcFindings(findings)
          return
        }
        setBcErr(err.status === 503
          ? 'Business Central integration is turned off (BC_ENABLED=false).'
          : (err.message || 'Could not build the BC payload.'))
      })
  }

  function confirmSplit(finding) {
    const p = finding.proposal
    if (!p) return
    setConfirming(true); setBcErr('')
    confirmVendorAddress(id, p.address_1, p.address_2)
      .then(() => { setConfirming(false); loadRecord(); fetchBcPayload() })
      .catch(err => {
        setConfirming(false)
        if (err.code === 'AUTH_EXPIRED') { navigate('/', { replace: true }); return }
        setBcErr(err.message || 'Could not confirm the address.')
      })
  }

  function copyPayload() {
    if (bc) navigator.clipboard?.writeText(JSON.stringify(bc, null, 2))
  }

  function downloadPayload() {
    if (!bc) return
    const blob = new Blob(
      [JSON.stringify({ target_url: bc.target_url, method: 'POST', payload: bc.payload }, null, 2)],
      { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    a.download = `${kind}_${id}_bc_${timestamp}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  function submitBcNo() {
    if (!bcNoInput.trim()) return
    setMarking(true); setBcErr('')
    cfg.bcMark(id, bcNoInput.trim())
      .then(() => { setMarking(false); loadRecord(); fetchBcPayload() })
      .catch(err => {
        setMarking(false)
        if (err.code === 'AUTH_EXPIRED') { navigate('/', { replace: true }); return }
        setBcErr(err.status === 409 ? `This ${cfg.title.toLowerCase()} is already marked as pushed.` : (err.message || 'Could not save.'))
      })
  }

  const isPushed = rec?.bc_status === 'pushed'

  return (
    <>
      <NavBar />
      <div className="page-wrapper">
        <main className="page-content">

          <a className="back-link" onClick={() => navigate(`/records/${kind}`)} style={{ cursor: 'pointer' }}>
            ‹ Saved {cfg.title}s
          </a>

          {error && <p className="records-error">{error}</p>}
          {!rec && !error && <p className="records-empty">Loading…</p>}

          {rec && (
            <>
              <div className="record-header-row">
                <h1 className="page-title" style={{ marginBottom: 0 }}>
                  {rec[cfg.nameKey] || `${cfg.title} #${rec.id}`}
                </h1>
                {!editing && (
                  <div className="record-header-actions">
                    <button className="btn btn-secondary" onClick={startEdit}>Edit</button>
                    <button className="btn btn-danger-outline" onClick={() => setConfirmDelete(true)}>Delete</button>
                  </div>
                )}
              </div>

              <div className="record-meta">
                <span>Ref #{rec.id}</span>
                <span className={`badge badge--${isPushed ? 'success' : 'neutral'}`}>
                  BC: {rec.bc_status || 'not_pushed'}{rec.bc_no ? ` (${rec.bc_no})` : ''}
                </span>
                <span>Created {fmtDate(rec.created_at)}</span>
                {rec.updated_at && rec.updated_at !== rec.created_at && (
                  <span>Updated {fmtDate(rec.updated_at)}</span>
                )}
              </div>

              {editing && isPushed && (
                <p className="records-review-note">
                  This record is already marked as pushed to Business Central. Editing it here
                  does <strong>not</strong> update Business Central — the two will be out of sync.
                </p>
              )}

              {editErr && <p className="records-error">{editErr}</p>}

              <div className="record-view">
                {cfg.groups.map(([groupName, fields]) => (
                  <section key={groupName} className="record-group">
                    <h2 className="record-group-title">{groupName}</h2>
                    <dl className="record-grid">
                      {fields.map(([key, label]) => (
                        <div key={key} className="record-row">
                          <dt>{label}{editing && key === requiredKey ? ' *' : ''}</dt>
                          <dd>
                            {editing ? (
                              key === 'type' ? (
                                <select
                                  className="form-input"
                                  value={form[key] ?? 'Services'}
                                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                                >
                                  {TYPE_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                                </select>
                              ) : (
                                <input
                                  className="form-input"
                                  value={form[key] ?? ''}
                                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                                />
                              )
                            ) : (
                              rec[key] ? String(rec[key]) : <span className="val-absent">—</span>
                            )}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </section>
                ))}
              </div>

              {editing && (
                <div className="record-edit-bar">
                  <button className="btn btn-secondary" disabled={saving} onClick={() => setEditing(false)}>
                    Cancel
                  </button>
                  <button className="btn btn-primary" disabled={saving} onClick={saveEdit}>
                    {saving ? 'Saving…' : 'Save changes'}
                  </button>
                </div>
              )}

              {!editing && (
                <section className="record-group bc-panel">
                  <h2 className="record-group-title">Business Central</h2>

                  {isPushed ? (
                    <p className="bc-pushed-note">
                      Pushed to Business Central{rec.bc_no ? ` as ${rec.bc_no}` : ''}
                      {rec.bc_synced_at ? ` on ${fmtDate(rec.bc_synced_at)}` : ''}.
                    </p>
                  ) : (
                    <>
                      <p className="bc-help">
                        The portal cannot reach Business Central directly. Get the payload,
                        run <code>scripts/push_to_bc.ps1</code> on a VPN machine, then record
                        the No. it returns.
                      </p>

                      {!bc && !bcFindings && (
                        <button className="btn btn-secondary" onClick={fetchBcPayload}>
                          Get BC payload
                        </button>
                      )}

                      {bcErr && <p className="records-error" style={{ marginTop: 12 }}>{bcErr}</p>}

                      {bcFindings && (
                        <div className="bc-findings">
                          <p className="bc-findings-title">Not ready for Business Central yet</p>
                          {bcFindings.map((f, i) => {
                            const lineSplit = f.before && f.proposal && 'address_1' in f.proposal
                            const open = f.automation_class === 'BLOCK_SUBMISSION'
                              || (f.automation_class === 'MANUAL_REVIEW' && !f.confirmed)
                            return (
                              <div key={i} className={`bc-finding ${open ? 'is-open' : 'is-done'}`}>
                                <div className="bc-finding-head">
                                  <span className="bc-finding-label">
                                    {BC_REASON_LABELS[f.reason_code] || f.reason_code}
                                  </span>
                                  <span className="bc-finding-field">{BC_FIELD_LABELS[f.field] || f.field}</span>
                                </div>
                                {f.detail && <p className="bc-help" style={{ margin: '4px 0 8px' }}>{f.detail}</p>}

                                {lineSplit && (
                                  <table className="bc-beforeafter">
                                    <thead><tr><th></th><th>Before</th><th>After</th></tr></thead>
                                    <tbody>
                                      {['address_1', 'address_2'].map(k => (
                                        <tr key={k}>
                                          <th>{BC_FIELD_LABELS[k]}</th>
                                          <td>{f.before[k] || <em>empty</em>}<span className="bc-len">{(f.before[k] || '').length}</span></td>
                                          <td>{f.proposal[k] || <em>empty</em>}<span className="bc-len">{(f.proposal[k] || '').length}</span></td>
                                        </tr>
                                      ))}
                                      {(f.before.address_3 || f.before.address_4) && (
                                        <tr>
                                          <th>Address 3 / 4</th>
                                          <td>{[f.before.address_3, f.before.address_4].filter(Boolean).join(', ')}</td>
                                          <td><em>merged into Address 2</em></td>
                                        </tr>
                                      )}
                                    </tbody>
                                  </table>
                                )}

                                {open && (
                                  <div className="bc-finding-actions">
                                    {lineSplit && (
                                      <button className="btn btn-primary" disabled={confirming} onClick={() => confirmSplit(f)}>
                                        {confirming ? 'Confirming…' : 'Confirm new split'}
                                      </button>
                                    )}
                                    <button className="btn btn-secondary" onClick={startEdit}>Edit manually</button>
                                  </div>
                                )}
                                {open && f.proposal === null && (
                                  <p className="bc-help" style={{ margin: '6px 0 0' }}>
                                    No automatic fix keeps every word of the address. Nothing is ever cut off:
                                    edit the lines so they fit, then get the payload again.
                                  </p>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      )}

                      {bc && (
                        <>
                          <div className="bc-payload-actions">
                            <button className="btn btn-secondary" onClick={downloadPayload}>Download JSON</button>
                            <button className="btn btn-secondary" onClick={copyPayload}>Copy</button>
                          </div>
                          <pre className="bc-payload-pre">{JSON.stringify(bc.payload, null, 2)}</pre>
                          <p className="bc-help" style={{ marginTop: 4 }}>
                            POST target: <code>{bc.target_url}</code>
                          </p>

                          <div className="bc-mark-row">
                            <input
                              className="form-input"
                              placeholder="BC No. returned, e.g. EMPV/0123"
                              value={bcNoInput}
                              onChange={e => setBcNoInput(e.target.value)}
                            />
                            <button className="btn btn-primary" disabled={marking || !bcNoInput.trim()} onClick={submitBcNo}>
                              {marking ? 'Saving…' : 'Mark as pushed'}
                            </button>
                          </div>
                        </>
                      )}
                    </>
                  )}
                </section>
              )}

              {confirmDelete && (
                <div className="modal-backdrop" onClick={() => !deleting && setConfirmDelete(false)}>
                  <div className="modal-card" onClick={e => e.stopPropagation()}>
                    <h3>Delete this {cfg.title.toLowerCase()}?</h3>
                    <p>
                      Ref #{rec.id} — {rec[cfg.nameKey] || '(no name)'}. This permanently removes
                      the record from the portal.
                      {isPushed && ' It has already been pushed to Business Central; that record in BC is not affected.'}
                    </p>
                    <div className="modal-actions">
                      <button className="btn btn-secondary" disabled={deleting} onClick={() => setConfirmDelete(false)}>
                        Cancel
                      </button>
                      <button className="btn btn-danger" disabled={deleting} onClick={doDelete}>
                        {deleting ? 'Deleting…' : 'Delete'}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

        </main>
      </div>
    </>
  )
}
