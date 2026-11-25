import { api } from '../api.js'
import { statusColor } from '../utils.js'

export default function Controls({ data, setNotice, setHighlight, go }) {
  const copyClarification = async () => {
    const { message } = await api.clarificationMessage('draft-041')
    try { await navigator.clipboard.writeText(message) } catch { /* presse-papiers indisponible */ }
    setNotice(`Message prêt à copier : ${message}`)
  }

  return (
    <section>
      <header className="mb-5">
        <h2 className="text-xl font-bold">Contrôles et anomalies</h2>
        <p className="text-sm text-slate-500">Une anomalie bloquante empêche la validation. Sa résolution est tracée.</p>
      </header>

      <div className="space-y-3">
        {data.anomalies.map((anomaly) => (
          <article key={anomaly.id} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <code className="rounded bg-slate-100 px-2 py-1 text-xs font-bold">{anomaly.code}</code>
                  <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${anomaly.severity === 'BLOQUANTE' ? 'bg-red-100 text-red-800' : 'bg-amber-100 text-amber-800'}`}>
                    {anomaly.severity}
                  </span>
                </div>
                <p className="mt-2 text-sm">{anomaly.message}</p>
              </div>
              <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${statusColor(anomaly.status)}`}>{anomaly.status}</span>
            </div>
            <div className="mt-3 flex gap-2">
              <button onClick={() => setHighlight(anomaly.field)} className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100">
                Voir la source
              </button>
              {anomaly.status !== 'RESOLUE' && (
                <button onClick={() => go('reconciliation')} className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white hover:bg-slate-700">
                  Résoudre
                </button>
              )}
            </div>
          </article>
        ))}
      </div>

      <div className="mt-5 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-bold">Message de clarification</h3>
        <p className="mt-1 text-xs text-slate-500">Pour l'IFU absent : on demande la donnée, on ne la déduit jamais du nom.</p>
        <button onClick={copyClarification} className="mt-3 rounded border border-slate-300 px-3 py-2 text-xs font-medium hover:bg-slate-100">
          Copier le message
        </button>
      </div>
    </section>
  )
}
