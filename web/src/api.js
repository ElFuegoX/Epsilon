// Client HTTP unique. Voir docs/API.md (contrat écrit par Melon, consommé par Jean-Marie).
// VITE_USE_MOCK=false bascule sur l'API réelle sans modifier les écrans.
import { mockRequest } from './mock.js'

export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
export const DEFAULT_ROLE = import.meta.env.VITE_ROLE || 'dirigeant'
let currentRole = DEFAULT_ROLE

export function setRole(role) {
  currentRole = role
}

function messageFrom(res, text) {
  try {
    const data = JSON.parse(text)
    return data.detail || data.message || `${res.status} ${res.statusText}`
  } catch {
    return `${res.status} ${res.statusText}`
  }
}

export async function request(path, { method = 'GET', body, formData, role = currentRole } = {}) {
  if (USE_MOCK) return mockRequest(path, { method, body, formData, role })

  const headers = { 'X-Role': role }
  let payload
  if (formData) {
    payload = formData
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: payload,
  })
  const text = await res.text()
  if (!res.ok) throw new Error(messageFrom(res, text))
  return text ? JSON.parse(text) : null
}

export const api = {
  health: () => request('/health'),
  listDocuments: () => request('/documents'),
  getDocument: (id) => request(`/documents/${id}`),
  importFile: (file, { canal = 'upload', typePiece } = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    if (canal) fd.append('canal', canal)
    if (typePiece) fd.append('type_piece', typePiece)
    return request('/documents', { method: 'POST', formData: fd })
  },
  importText: ({ nom, texte, type = 'message', canal = 'whatsapp_sim' }) =>
    request('/documents', { method: 'POST', body: { nom, texte, type, canal } }),
  extract: (id) => request(`/documents/${id}/extract`, { method: 'POST' }),
  listDrafts: () => request('/drafts'),
  getDraft: (id) => request(`/drafts/${id}`),
  patchDraft: (id, patch) => request(`/drafts/${id}`, { method: 'PATCH', body: patch }),
  addLine: (draftId, line) => request(`/drafts/${draftId}/lines`, { method: 'POST', body: line }),
  patchLine: (lineId, patch) => request(`/lines/${lineId}`, { method: 'PATCH', body: patch }),
  listAnomalies: (draftId) => request(`/drafts/${draftId}/anomalies`),
  resolveAnomaly: (id, justification) =>
    request(`/anomalies/${id}/resolve`, {
      method: 'POST',
      body: justification ? { justification } : undefined,
    }),
  clarificationMessage: (draftId) => request(`/drafts/${draftId}/clarification-message`, { method: 'POST' }),
  validate: (draftId) => request(`/drafts/${draftId}/validate`, { method: 'POST' }),
  listInvoices: () => request('/invoices'),
  getInvoice: (id) => request(`/invoices/${id}`),
  invoicePdfUrl: (id) => `${API_URL}/invoices/${id}/pdf`,
  issue: (id, channel) => request(`/invoices/${id}/issue`, { method: 'POST', body: { channel } }),
  creditNote: (id, body) => request(`/invoices/${id}/credit-notes`, { method: 'POST', body }),
  audit: () => request('/audit'),
  verifyAudit: () => request('/audit/verify'),
  auditCsvUrl: () => `${API_URL}/audit/export.csv`,
  clients: () => request('/referentials/clients'),
  items: () => request('/referentials/items'),
  reset: () => request('/admin/reset', { method: 'POST' }),
}
