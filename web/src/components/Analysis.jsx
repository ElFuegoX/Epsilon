import { useState } from 'react'
import SourceViewer from './SourceViewer'
import { api } from '../api.js'
import { money } from '../utils.js'

const LABELS = {
  reference: 'Référence',
  date: 'Date',
  client_name: 'Client',
  client_ifu: 'IFU',
  line_1_price: 'Ligne 1 · prix unitaire',
  line_2_price: 'Ligne 2 · prix unitaire',
  line_3_price: 'Ligne 3 · prix unitaire',
  printed_ht: 'Total HT imprimé',
}

function reliabilityBadge(score, absent) {
  if (absent) return { label: 'Manquant', cls: 'bg-red-100 text-red-800' }
  if (score == null) return { label: 'Lu', cls: 'bg-slate-100 text-slate-600' }
  if (score >= 0.9) return { label: 'Fiable', cls: 'bg-emerald-100 text-emerald-800' }
  if (score >= 0.8) return { label: 'À vérifier', cls: 'bg-amber-100 text-amber-800' }
  return { label: 'Incertain', cls: 'bg-red-100 text-red-800' }
}

export default function Analysis({ document: doc, draft, highlight, setHighlight, run, setNotice, go }) {
  const [showTech, setShowTech] = useState(false)

  const copyClarification = async () => {
    if (!draft?.id) return
    await run(async () => {
      const { message } = await api.clarificationMessage(draft.id)
      try { await navigator.clipboard.writeText(message) } catch { /* presse-papiers indisponible */ }
      setNotice({ type: 'success', text: `Message prêt à copier : ${message}` })
    })
  }

  const fieldKeys = Array.from(
    new Set([...Object.keys(LABELS), ...Object.keys(doc?.fields || {})])
  )

  return (
    <section>
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Analyse · vérification de la pièce</h2>
          <p className="text-sm text-slate-500">Cliquez sur une information pour voir exactement où elle a été lue sur le document. Aucune donnée absente n'est inventée.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowTech((v) => !v)}
            className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-100"
          >
            {showTech ? 'Masquer détails techniques' : 'Détails techniques (Audit)'}
          </button>
          <button onClick={() => go('lines')} className="rounded bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700">
            Voir les lignes →
          </button>
        </div>
      </header>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <SourceViewer document={doc} highlight={highlight} onSelectField={setHighlight} showTech={showTech} />
        </div>

        <div className="space-y-4">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-bold">Informations lues sur la pièce</h3>
              <span className="text-[11px] text-slate-400">Fiable · À vérifier · Manquant</span>
            </div>
            <dl className="divide-y divide-slate-100 text-sm">
              {fieldKeys.map((key) => {
                const field = doc?.fields?.[key]
                const label = LABELS[key] || key
                const absent = !field || field.value == null
                const badge = reliabilityBadge(field?.confidence, absent)
                const pct = field?.confidence != null ? `${Math.round(field.confidence * 100)} %` : null
                return (
                  <div key={key} className="flex items-center justify-between gap-3 py-2">
                    <dt className="flex items-center gap-2 text-slate-600">
                      <span>{label}</span>
                      {showTech && field?.method && (
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-500">
                          {field.method}
                        </span>
                      )}
                    </dt>
                    <dd className="flex items-center gap-2 text-right">
                      {absent ? (
                        <span className="rounded bg-red-50 px-2 py-1 text-xs font-medium text-red-700">— absent de la pièce —</span>
                      ) : (
                        <button
                          onClick={() => setHighlight(key)}
                          className={`rounded px-2 py-1 font-medium hover:bg-amber-100 ${highlight === key ? 'bg-amber-200 text-amber-950' : 'text-slate-900'}`}
                        >
                          {typeof field.value === 'number' && key !== 'reference' ? money(field.value) : field.value}
                          {field.page && <span className="ml-1.5 text-[10px] text-slate-400">p.{field.page}</span>}
                        </button>
                      )}
                      <span
                        title={pct ? `Indice de confiance : ${pct}` : ''}
                        className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${badge.cls}`}
                      >
                        {showTech && pct ? `${badge.label} (${pct})` : badge.label}
                      </span>
                    </dd>
                  </div>
                )
              })}
            </dl>
          </div>

          {(doc?.fields?.client_ifu?.motif === 'ABSENT_DE_LA_PIECE' || doc?.fields?.['client.ifu']?.motif === 'ABSENT_DE_LA_PIECE') && (
            <div className="rounded-lg border border-red-300 bg-red-50 p-4">
              <p className="text-sm font-semibold text-red-800">Information obligatoire absente : IFU du client</p>
              <p className="mt-1 text-xs text-red-700">WÉMA ne devine jamais un numéro fiscal : envoyez un message rapide au client pour le récupérer.</p>
              <button onClick={copyClarification} className="mt-3 rounded bg-red-700 px-3 py-2 text-xs font-medium text-white hover:bg-red-800">
                Copier le message de demande au client
              </button>
            </div>
          )}

          {draft && (
            <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
              <h3 className="mb-2 text-sm font-bold">Brouillon préparé</h3>
              <p><span className="text-slate-500">Référence :</span> {draft.reference || draft.id}</p>
              <p><span className="text-slate-500">Client :</span> {draft.client?.name || draft.client_detail?.raison_sociale || '— absent de la pièce —'}</p>
              <p><span className="text-slate-500">Lignes :</span> {draft.lines?.length ?? 0}</p>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
