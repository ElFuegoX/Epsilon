import { useState } from 'react'
import { api } from '../api.js'
import { statusColor } from '../utils.js'

export default function Controls({ data, draft, run, setNotice, setHighlight, go }) {
  const [resolvingId, setResolvingId] = useState(null)
  const [justification, setJustification] = useState('')

  const openCount = data.anomalies.filter((a) => a.status !== 'RESOLUE').length

  const copyClarification = async () => {
    if (!draft?.id) return
    await run(async () => {
      const { message } = await api.clarificationMessage(draft.id)
      try { await navigator.clipboard.writeText(message) } catch { /* presse-papiers indisponible */ }
      setNotice({ type: 'success', text: `Message prêt à copier : ${message}` })
    })
  }

  const openSource = (field) => {
    setHighlight(field)
    go('analysis')
  }

  const confirmResolve = async (anomalyId) => {
    const motif = justification.trim() || 'Vérifié et validé par opérateur'
    await run(async () => {
      await api.resolveAnomaly(anomalyId, motif)
      setResolvingId(null)
      setJustification('')
      setNotice({ type: 'success', text: 'Anomalie marquée comme résolue (trace enregistrée dans le journal).' })
    })
  }

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">Anomalies à traiter</h2>
          <p className="text-xs text-slate-500">Chaque anomalie bloquante protège contre une erreur de facturation.</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-bold ${openCount > 0 ? 'bg-red-100 text-red-800' : 'bg-emerald-100 text-emerald-800'}`}>
          {openCount > 0 ? `${openCount} à traiter` : 'Tout est réglé ✓'}
        </span>
      </header>

      {data.anomalies.length === 0 ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 text-sm font-medium text-emerald-900">
          Aucune anomalie détectée sur ce dossier : il est prêt pour la validation.
        </div>
      ) : (
        <div className="space-y-3">
          {data.anomalies.map((anomaly) => {
            const isBlocking = anomaly.severity === 'BLOQUANTE' || anomaly.severity === 'BLOQUANT'
            const isResolved = anomaly.status === 'RESOLUE'
            const isEditing = resolvingId === anomaly.id
            return (
              <article
                key={anomaly.id}
                className={`rounded-2xl border p-4 shadow-sm transition ${
                  isResolved
                    ? 'border-emerald-200 bg-emerald-50/50'
                    : isBlocking
                      ? 'border-red-200 bg-white'
                      : 'border-amber-200 bg-white'
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <code className="rounded-lg bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-700">{anomaly.code}</code>
                      <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold ${isBlocking ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-800'}`}>
                        {anomaly.severity}
                      </span>
                    </div>
                    <p className="mt-2 text-sm font-medium text-slate-900">{anomaly.message}</p>
                  </div>
                  <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${statusColor(anomaly.status)}`}>
                    {anomaly.status}
                  </span>
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  {anomaly.field && (
                    <button
                      type="button"
                      onClick={() => openSource(anomaly.field)}
                      className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
                    >
                      Voir sur la pièce →
                    </button>
                  )}
                  {!isResolved && !isEditing && (
                    <button
                      type="button"
                      onClick={() => { setResolvingId(anomaly.id); setJustification('') }}
                      className="rounded-xl bg-emerald-600 px-3.5 py-1.5 text-xs font-bold text-white hover:bg-emerald-700"
                    >
                      Résoudre ici
                    </button>
                  )}
                  {!isResolved && anomaly.code === 'QUANTITY_MISMATCH' && (
                    <button
                      type="button"
                      onClick={() => go('reconciliation')}
                      className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                    >
                      Trancher la livraison
                    </button>
                  )}
                </div>

                {isEditing && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-slate-50 p-3">
                    <input
                      type="text"
                      value={justification}
                      onChange={(e) => setJustification(e.target.value)}
                      placeholder="Motif de la décision (tracé dans le journal)..."
                      className="min-w-[200px] flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs focus:border-emerald-500 focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => confirmResolve(anomaly.id)}
                      className="rounded-xl bg-emerald-600 px-3.5 py-2 text-xs font-bold text-white hover:bg-emerald-700"
                    >
                      Confirmer
                    </button>
                    <button
                      type="button"
                      onClick={() => setResolvingId(null)}
                      className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100"
                    >
                      Annuler
                    </button>
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div>
          <h3 className="text-sm font-bold text-slate-900">Besoin d’une info du client ?</h3>
          <p className="text-xs text-slate-500">Génère un message WhatsApp prêt à envoyer pour récupérer les mentions absentes.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={copyClarification}
            disabled={!draft?.id}
            className="rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2 text-xs font-bold text-slate-800 hover:bg-slate-100 disabled:opacity-50"
          >
            Copier le message
          </button>
          <button
            type="button"
            onClick={() => go('validation')}
            className={`rounded-xl px-4 py-2 text-xs font-bold transition ${
              openCount === 0
                ? 'bg-emerald-600 text-white shadow-sm hover:bg-emerald-700'
                : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
            }`}
          >
            Passer à la validation →
          </button>
        </div>
      </div>
    </section>
  )
}
