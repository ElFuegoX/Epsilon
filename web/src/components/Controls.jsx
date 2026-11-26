import { useState } from 'react'
import { api } from '../api.js'
import { statusColor } from '../utils.js'

export default function Controls({ data, draft, run, setNotice, setHighlight, go }) {
  const [resolvingId, setResolvingId] = useState(null)
  const [justification, setJustification] = useState('')

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
    <section>
      <header className="mb-5">
        <h2 className="text-xl font-bold">Contrôles et anomalies</h2>
        <p className="text-sm text-slate-500">Une anomalie bloquante empêche la validation. Sa résolution est tracée dans le journal.</p>
      </header>

      {data.anomalies.length === 0 ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-900">
          Aucune anomalie détectée sur ce brouillon : il est prêt pour la validation.
        </div>
      ) : (
        <div className="space-y-3">
          {data.anomalies.map((anomaly) => {
            const isBlocking = anomaly.severity === 'BLOQUANTE' || anomaly.severity === 'BLOQUANT'
            const isResolved = anomaly.status === 'RESOLUE'
            const isEditing = resolvingId === anomaly.id
            return (
              <article key={anomaly.id} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <code className="rounded bg-slate-100 px-2 py-1 text-xs font-bold">{anomaly.code}</code>
                      <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${isBlocking ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-800'}`}>
                        {anomaly.severity}
                      </span>
                    </div>
                    <p className="mt-2 text-sm">{anomaly.message}</p>
                  </div>
                  <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${statusColor(anomaly.status)}`}>{anomaly.status}</span>
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  {anomaly.field && (
                    <button
                      type="button"
                      onClick={() => openSource(anomaly.field)}
                      className="rounded border border-slate-300 px-3 py-1 text-xs font-medium hover:bg-slate-100"
                    >
                      Voir la source →
                    </button>
                  )}
                  {!isResolved && !isEditing && (
                    <button
                      type="button"
                      onClick={() => { setResolvingId(anomaly.id); setJustification('') }}
                      className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white hover:bg-slate-700"
                    >
                      Résoudre ici
                    </button>
                  )}
                  {!isResolved && anomaly.code === 'QUANTITY_MISMATCH' && (
                    <button
                      type="button"
                      onClick={() => go('reconciliation')}
                      className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100"
                    >
                      Ouvrir le rapprochement
                    </button>
                  )}
                </div>

                {isEditing && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 rounded bg-slate-50 p-3">
                    <input
                      type="text"
                      value={justification}
                      onChange={(e) => setJustification(e.target.value)}
                      placeholder="Motif / justification de la résolution..."
                      className="min-w-[220px] flex-1 rounded border border-slate-300 bg-white px-3 py-1.5 text-xs"
                    />
                    <button
                      type="button"
                      onClick={() => confirmResolve(anomaly.id)}
                      className="rounded bg-emerald-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-800"
                    >
                      Confirmer
                    </button>
                    <button
                      type="button"
                      onClick={() => setResolvingId(null)}
                      className="rounded border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100"
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

      <div className="mt-5 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-bold">Message de clarification</h3>
        <p className="mt-1 text-xs text-slate-500">Pour toute donnée obligatoire absente (ex. IFU) : on la demande au client au lieu de la deviner.</p>
        <button
          type="button"
          onClick={copyClarification}
          disabled={!draft?.id}
          className="mt-3 rounded border border-slate-300 px-3 py-2 text-xs font-medium hover:bg-slate-100 disabled:opacity-50"
        >
          Copier le message
        </button>
      </div>
    </section>
  )
}
