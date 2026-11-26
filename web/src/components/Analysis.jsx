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
    <section className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">Vérification de la pièce</h2>
          <p className="text-xs text-slate-500">Touchez une valeur pour surligner sa source exacte sur le document.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowTech((v) => !v)}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50"
          >
            {showTech ? 'Masquer audit' : 'Détails audit'}
          </button>
          <button
            type="button"
            onClick={() => go('controls')}
            className="rounded-xl bg-emerald-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-emerald-700"
          >
            Voir les anomalies →
          </button>
        </div>
      </header>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <SourceViewer document={doc} highlight={highlight} onSelectField={setHighlight} showTech={showTech} />
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900">Informations lues</h3>
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
                  <div key={key} className="flex items-center justify-between gap-3 py-2.5">
                    <dt className="flex items-center gap-2 text-xs font-medium text-slate-600">
                      <span>{label}</span>
                      {showTech && field?.method && (
                        <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-500">
                          {field.method}
                        </span>
                      )}
                    </dt>
                    <dd className="flex items-center gap-2 text-right">
                      {absent ? (
                        <span className="rounded-lg bg-red-50 px-2 py-1 text-xs font-semibold text-red-700">— absent —</span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setHighlight(key)}
                          className={`rounded-lg px-2 py-1 text-xs font-bold tabular-nums transition ${
                            highlight === key ? 'bg-amber-200 text-amber-950' : 'text-slate-900 hover:bg-emerald-50'
                          }`}
                        >
                          {typeof field.value === 'number' && key !== 'reference' ? money(field.value) : field.value}
                          {field.page && <span className="ml-1.5 text-[10px] font-normal text-slate-400">p.{field.page}</span>}
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
            <div className="rounded-2xl border border-red-200 bg-red-50 p-4 shadow-sm">
              <p className="text-sm font-bold text-red-900">IFU du client absent de la pièce</p>
              <p className="mt-1 text-xs text-red-700">WÉMA ne devine jamais un numéro fiscal : envoyez la demande directement au client.</p>
              <button
                type="button"
                onClick={copyClarification}
                className="mt-3 w-full rounded-xl bg-emerald-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-emerald-700"
              >
                Copier le message WhatsApp de demande d’IFU
              </button>
            </div>
          )}

          {draft && (
            <div className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white p-4 text-xs shadow-sm">
              <div>
                <p className="font-bold text-slate-900">{draft.reference || draft.id}</p>
                <p className="text-slate-500">
                  {draft.client?.name || draft.client_detail?.raison_sociale || '— absent de la pièce —'} · {draft.lines?.length ?? 0} ligne(s)
                </p>
              </div>
              <button
                type="button"
                onClick={() => go('lines')}
                className="rounded-xl border border-slate-200 px-3 py-1.5 font-semibold text-emerald-700 hover:bg-emerald-50"
              >
                Éditer les lignes →
              </button>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
