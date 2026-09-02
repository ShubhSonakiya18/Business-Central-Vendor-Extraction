/**
 * api.js — Central API service layer
 *
 * All backend calls go through here so components stay clean.
 * Proxied by Vite to http://127.0.0.1:8000 in development.
 *
 * Key endpoint: POST /extract
 *   Body (multipart/form-data):
 *     documents      — one or more File objects (PDF, DOCX, image)
 *     vendor_template — optional Excel template File
 *   Response:
 *     {
 *       run_id: string,
 *       values: { [fieldName]: value },
 *       fields: { [fieldName]: { value, confidence, source, flagged } },
 *       needs_review: string[],
 *       summary: { filled, total_fields, … },
 *       verification: { … } | null,
 *       timings: { load, extract, total },
 *     }
 */

// Empty in dev: vite.config.js proxies these paths to 127.0.0.1:8000.
// Set VITE_API_URL at build time (e.g. in Netlify) to point a static build at
// a backend on another origin, such as an ngrok URL -- see ar-portal/.env.example.
const BASE = import.meta.env.VITE_API_URL ?? ''

// Free ngrok tunnels serve an HTML "you are about to visit..." interstitial
// on a browser's first request to a given tunnel, which breaks fetch() --
// the response is HTML, not the JSON the caller expects. This header
// suppresses it. Harmless (ignored) against a same-origin dev proxy or any
// non-ngrok backend, so it is sent unconditionally rather than only when
// VITE_API_URL looks like an ngrok URL.
const SKIP_NGROK_WARNING = { 'ngrok-skip-browser-warning': 'true' }

/**
 * Run OCR extraction on uploaded documents.
 *
 * @param {File[]} documentFiles  – PDFs / images / DOCX files to extract from
 * @param {File|null} templateFile – optional Excel template to fill
 * @param {string} mapping        – excel mapping name (default: vendor_creation_v1)
 * @returns {Promise<object>}     – backend JSON response (see header above)
 */
export async function extractDocuments(documentFiles, templateFile = null, mapping = 'vendor_creation_v1') {
  const formData = new FormData()

  documentFiles.forEach(f => formData.append('documents', f))
  if (templateFile) formData.append('vendor_template', templateFile)
  formData.append('mapping', mapping)
  formData.append('models', 'small')

  const res = await fetch(`${BASE}/extract`, {
    method: 'POST',
    headers: SKIP_NGROK_WARNING,
    body: formData,
  })

  if (!res.ok) {
    let errBody = {}
    try { errBody = await res.json() } catch (_) { }
    const msg = errBody.error || errBody.detail || `Server error ${res.status}`
    throw new Error(msg)
  }

  return res.json()
}

/**
 * Reload a previously processed run by its run_id.
 * Useful if the page is refreshed after extraction.
 *
 * @param {string} runId
 * @returns {Promise<object>}
 */
export async function getRunResult(runId) {
  const res = await fetch(`${BASE}/results/${runId}/json`, { headers: SKIP_NGROK_WARNING })
  if (!res.ok) throw new Error(`Could not load run ${runId}`)
  return res.json()
}

/**
 * Returns a URL that, when navigated to, downloads a run artifact.
 *
 * @param {string} runId
 * @param {'xlsx'|'json'|'report'|'extraction'|'spans'} kind
 * @returns {string} URL
 */
export function downloadUrl(runId, kind) {
  return `${BASE}/download/${runId}/${kind}`
}

/**
 * Check that the backend is reachable and correctly configured.
 *
 * @returns {Promise<{status: string, fields: number, …}>}
 */
export async function checkHealth() {
  const res = await fetch(`${BASE}/health`, { headers: SKIP_NGROK_WARNING })
  if (!res.ok) throw new Error('Backend health check failed')
  return res.json()
}
