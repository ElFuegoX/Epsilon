// Données de démonstration déterministes, calquées sur docs/API.md et seeds/golden/DEV-2026-041.truth.json.
// Usage unique : VITE_USE_MOCK=true. Aucune valeur n'est inventée : les champs absents portent leur motif.

const copy = (value) => JSON.parse(JSON.stringify(value))
const now = '2026-11-25T08:12:00'

function createInitialState() {
  const fields = {
    reference: { value: 'DEV-2026-041', page: 1, bbox: { x: 6, y: 8, w: 26, h: 4 }, method: 'ocr', confidence: 0.99 },
    date: { value: '2026-11-18', page: 1, bbox: { x: 70, y: 8, w: 20, h: 4 }, method: 'ocr', confidence: 0.97 },
    client_name: { value: 'Ets Sossa Materiaux', page: 1, bbox: { x: 6, y: 18, w: 34, h: 4 }, method: 'llm', confidence: 0.93 },
    client_ifu: { value: null, motif: 'ABSENT_DE_LA_PIECE', page: 1, bbox: { x: 6, y: 24, w: 26, h: 4 }, method: 'llm', confidence: 0.41 },
    line_1_price: { value: 185000, page: 1, bbox: { x: 62, y: 40, w: 20, h: 4 }, method: 'llm', confidence: 0.91 },
    line_2_price: { value: 120000, page: 1, bbox: { x: 62, y: 48, w: 20, h: 4 }, method: 'llm', confidence: 0.89 },
    line_3_price: { value: 60000, page: 1, bbox: { x: 62, y: 56, w: 20, h: 4 }, method: 'llm', confidence: 0.86 },
    printed_ht: { value: 1020000, page: 1, bbox: { x: 62, y: 72, w: 22, h: 4 }, method: 'ocr', confidence: 0.95 },
  }

  return {
    documents: [
      {
        id: 'doc-041',
        reference: 'DEV-2026-041',
        type: 'devis',
        filename: 'DEV-2026-041.pdf',
        status: 'EXTRAIT',
        created_at: now,
        hash: '9c1f4a2e',
        fields,
        pageText: [
          { text: 'DEVIS DEV-2026-041', y: 8 },
          { text: 'Date : 18/11/2026', y: 8, align: 'right' },
          { text: 'Client : Ets Sossa Materiaux', y: 18 },
          { text: 'IFU : — absent de la pièce —', y: 24 },
          { text: '1  Banquette 3 places      4 x 185 000', y: 40 },
          { text: '2  Table basse chêne        2 x 120 000', y: 48 },
          { text: '3  Livraison et installation 1 x 60 000', y: 56 },
          { text: 'Total HT imprimé : 1 020 000', y: 72 },
        ],
      },
      {
        id: 'doc-wait',
        reference: 'CMD-2026-118',
        type: 'photo',
        filename: 'commande_photo.jpg',
        status: 'EN_ATTENTE_IA',
        created_at: now,
        hash: 'b7e20d91',
        fields: {},
        pageText: [],
      },
    ],
    drafts: [
      {
        id: 'draft-041',
        document_id: 'doc-041',
        reference: 'DEV-2026-041',
        date: '2026-11-18',
        client: { name: 'Ets Sossa Materiaux', ifu: null, missing: ['ifu'] },
        status: 'EN_ATTENTE',
        numero_previsionnel: 'FAC-2026-00042',
        lines: [
          { id: 'line-1', line_no: 1, description: 'Banquette 3 places', quantity: 4, delivered: 4, unit_price_ht: 185000, tax_rate: 18, line_total_ht: 740000, field: 'line_1_price' },
          { id: 'line-2', line_no: 2, description: 'Table basse chêne', quantity: 2, delivered: 2, unit_price_ht: 120000, tax_rate: 18, line_total_ht: 240000, field: 'line_2_price' },
          { id: 'line-3', line_no: 3, description: 'Livraison et installation', quantity: 1, delivered: 0, unit_price_ht: 60000, tax_rate: 18, line_total_ht: 60000, field: 'line_3_price' },
        ],
        printed_totals: { ht: 1020000, vat: 183600, ttc: 1203600 },
        recalculated_totals: { ht: 1040000, vat: 187200, ttc: 1227200 },
        ecart: { ht: 20000, vat: 3600, ttc: 23600 },
      },
    ],
    anomalies: [
      { id: 'an-1', draft_id: 'draft-041', code: 'MISSING_MANDATORY', severity: 'BLOQUANTE', message: 'IFU absent de la pièce', field: 'client_ifu', status: 'OUVERTE' },
      { id: 'an-2', draft_id: 'draft-041', code: 'ARITHMETIC_MISMATCH', severity: 'BLOQUANTE', message: 'Écart de 20 000 FCFA sur le total HT imprimé', field: 'printed_ht', status: 'OUVERTE' },
      { id: 'an-3', draft_id: 'draft-041', code: 'QUANTITY_MISMATCH', severity: 'BLOQUANTE', message: 'Ligne 3 : livré 0 / commandé 1', field: 'line_3_price', status: 'OUVERTE' },
    ],
    invoices: [],
    credit_notes: [],
    audit: [
      { id: 'evt-1', action: 'DOCUMENT_IMPORTE', actor: 'assistante', target: 'doc-041', at: now, hash: 'a1' },
      { id: 'evt-2', action: 'EXTRACTION_TERMINEE', actor: 'systeme', target: 'doc-041', at: now, hash: 'a2' },
    ],
    clients: [
      { id: 'cli-1', name: 'Ets Sossa Materiaux', ifu: null, source: 'referentiel' },
      { id: 'cli-2', name: 'Menuiserie Kora', ifu: '123456789', source: 'referentiel' },
    ],
    items: [
      { id: 'art-1', name: 'Banquette 3 places', price: 185000 },
      { id: 'art-2', name: 'Table basse chêne', price: 120000 },
      { id: 'art-3', name: 'Livraison et installation', price: 60000 },
    ],
  }
}

let db = createInitialState()
const clone = () => copy(db)

export function resetMock() {
  db = createInitialState()
  return clone()
}

export function mockRequest(path, { method = 'GET', body } = {}) {
  const result = (value) => Promise.resolve(copy(value))
  const parts = path.split('/').filter(Boolean)

  if (path === '/health') return result({ status: 'ok', mode: 'mock' })
  if (path === '/admin/reset' && method === 'POST') { db = createInitialState(); return result({ reset: true }) }

  if (path === '/documents' && method === 'GET') return result({ items: db.documents })
  if (path === '/documents' && method === 'POST') return result(db.documents[0])
  if (parts[0] === 'documents' && parts.length === 2 && method === 'GET') {
    return result(db.documents.find((d) => d.id === parts[1]) || null)
  }
  if (parts[0] === 'documents' && parts[2] === 'extract' && method === 'POST') {
    const doc = db.documents.find((d) => d.id === parts[1])
    if (doc) doc.status = 'EXTRAIT'
    return result(doc)
  }

  if (path === '/drafts' && method === 'GET') return result({ items: db.drafts })
  if (parts[0] === 'drafts' && parts.length === 2 && method === 'GET') {
    return result(db.drafts.find((d) => d.id === parts[1]) || null)
  }
  if (parts[0] === 'drafts' && parts.length === 2 && method === 'PATCH') {
    const draft = db.drafts.find((d) => d.id === parts[1])
    if (draft) Object.assign(draft, body)
    return result(draft)
  }
  if (parts[0] === 'drafts' && parts[2] === 'lines' && method === 'POST') {
    const draft = db.drafts.find((d) => d.id === parts[1])
    const line = { id: `line-${Date.now()}`, line_no: draft.lines.length + 1, ...body }
    draft.lines.push(line)
    return result(line)
  }
  if (parts[0] === 'drafts' && parts[2] === 'anomalies' && method === 'GET') {
    return result({ items: db.anomalies.filter((a) => a.draft_id === parts[1]) })
  }
  if (parts[0] === 'drafts' && parts[2] === 'clarification-message' && method === 'POST') {
    return result({ message: "Bonjour, le devis DEV-2026-041 ne mentionne pas d'IFU. Pouvez-vous nous le transmettre ?" })
  }
  if (parts[0] === 'drafts' && parts[2] === 'validate' && method === 'POST') {
    const draft = db.drafts.find((d) => d.id === parts[1])
    if (db.invoices.some((i) => i.draft_id === draft.id)) {
      return Promise.reject(new Error('409 - brouillon déjà validé'))
    }
    draft.status = 'VALIDE'
    const invoice = {
      id: 'inv-42',
      draft_id: draft.id,
      numero: draft.numero_previsionnel,
      date: draft.date,
      client: draft.client,
      lines: draft.lines,
      totals: draft.recalculated_totals,
      status: 'VALIDEE',
      channel: null,
      issued_at: null,
      credit_notes: [],
    }
    db.invoices.push(invoice)
    db.audit.push({ id: `evt-${db.audit.length + 1}`, action: 'FACTURE_VALIDEE', actor: 'dirigeant', target: invoice.numero, at: now, hash: `a${db.audit.length + 1}` })
    return result(invoice)
  }

  if (parts[0] === 'lines' && parts.length === 2 && method === 'PATCH') {
    for (const draft of db.drafts) {
      const line = draft.lines.find((l) => l.id === parts[1])
      if (line) {
        Object.assign(line, body)
        line.line_total_ht = Math.round(line.quantity * line.unit_price_ht)
        draft.recalculated_totals.ht = draft.lines.reduce((sum, l) => sum + l.line_total_ht, 0)
        draft.recalculated_totals.vat = Math.round(draft.recalculated_totals.ht * 0.18)
        draft.recalculated_totals.ttc = draft.recalculated_totals.ht + draft.recalculated_totals.vat
        return result(line)
      }
    }
    return result(null)
  }

  if (parts[0] === 'anomalies' && parts[2] === 'resolve' && method === 'POST') {
    const anomaly = db.anomalies.find((a) => a.id === parts[1])
    if (anomaly) anomaly.status = 'RESOLUE'
    return result(anomaly)
  }

  if (path === '/invoices' && method === 'GET') return result({ items: db.invoices })
  if (parts[0] === 'invoices' && parts.length === 2 && method === 'GET') {
    return result(db.invoices.find((i) => i.id === parts[1]) || null)
  }
  if (parts[0] === 'invoices' && parts[2] === 'issue' && method === 'POST') {
    const invoice = db.invoices.find((i) => i.id === parts[1])
    invoice.channel = body.channel || 'email'
    invoice.status = 'EMISE'
    invoice.issued_at = now
    db.audit.push({ id: `evt-${db.audit.length + 1}`, action: 'FACTURE_EMISE', actor: 'assistante', target: invoice.numero, at: now, hash: `a${db.audit.length + 1}` })
    return result(invoice)
  }
  if (parts[0] === 'invoices' && parts[2] === 'credit-notes' && method === 'POST') {
    const invoice = db.invoices.find((i) => i.id === parts[1])
    const note = {
      id: `av-${db.credit_notes.length + 7}`,
      numero: `AV-2026-${String(db.credit_notes.length + 7).padStart(5, '0')}`,
      invoice_id: invoice.id,
      total_ttc: body.total_ttc ?? invoice.totals.ttc,
      motif: body.motif || 'avoir total',
    }
    db.credit_notes.push(note)
    invoice.credit_notes.push(note)
    db.audit.push({ id: `evt-${db.audit.length + 1}`, action: 'AVOIR_EMIS', actor: 'dirigeant', target: note.numero, at: now, hash: `a${db.audit.length + 1}` })
    return result(note)
  }

  if (path === '/audit' && method === 'GET') return result({ items: db.audit })
  if (path === '/audit/verify' && method === 'GET') return result({ valid: true, events: db.audit.length, detail: 'Chaîne SHA-256 intacte' })
  if (path === '/referentials/clients' && method === 'GET') return result({ items: db.clients })
  if (path === '/referentials/items' && method === 'GET') return result({ items: db.items })

  return Promise.reject(new Error(`404 - route mock inconnue : ${method} ${path}`))
}
