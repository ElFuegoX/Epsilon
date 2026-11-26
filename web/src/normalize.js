// Adaptateurs des réponses réelles vers la forme consommée par les écrans.
// Le mode démo (mock.js) produit déjà cette forme : aucun écran n'a à changer.
// Aucune valeur métier n'est inventée ici : on ne fait que renommer ou dériver.

const sansExtension = (nom) => String(nom || '').replace(/\.[^.]+$/, '')

export function normalizeDocument(doc) {
  if (!doc) return doc
  const fields = doc.fields || {}
  const reference =
    doc.reference || fields.reference?.value || sansExtension(doc.filename) || doc.id
  // Aperçu texte quand le PDF n'est pas encore disponible : on affiche les zones
  // réellement extraites, avec leur position, sans reconstituer la pièce.
  const pageText =
    doc.pageText ||
    Object.entries(fields)
      .filter(([, field]) => field?.bbox && field.value != null)
      .map(([key, field]) => ({ text: String(field.value), y: field.bbox.y, key }))
  return { ...doc, reference, pageText }
}

export function normalizeDraft(draft, documents = [], clients = []) {
  if (!draft) return draft
  const detail = draft.client_detail || null
  const clientId = detail?.id || draft.client
  const referentiel = clients.find((c) => c.id === clientId)
  const client = draft.client || (detail
    ? { ...detail, ...referentiel, name: detail.raison_sociale || referentiel?.name }
    : referentiel
      ? { ...referentiel, name: referentiel.name }
      : null)
  const document = documents.find((d) => d.id === (draft.document_id || draft.document))
  return {
    ...draft,
    reference: draft.reference || document?.reference || sansExtension(document?.filename) || draft.id,
    client,
    lines: (draft.lines || []).map((line) => ({
      ...line,
      field: line.field || `line_${line.line_no}_price`,
    })),
  }
}

export function normalizeInvoice(invoice, clients = []) {
  if (!invoice) return invoice
  const referentiel = clients.find((c) => c.id === invoice.client)
  return {
    ...invoice,
    client: invoice.client?.name ? invoice.client : (referentiel?.name || invoice.client || null),
  }
}
