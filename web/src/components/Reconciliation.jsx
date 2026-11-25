import { useState } from 'react'
import { api } from '../api.js'
import { money, statusColor } from '../utils.js'

export default function Reconciliation({ draft, data, run, setNotice }) {
  const [decisions, setDecisions] = useState({})

  const decide = (line, decision) => {
    setDecisions((prev) => ({ ...prev, [line.id]: decision }))
    setNotice(`Décision « ${decision} » enregistrée sur la ligne ${line.line_no}.`)
    if (line.delivered < line.quantity) {
      run(() => api.resolveAnomaly('an-3'))
    }
  }

  if (!draft) return <p className="text-sm text-slate-500">Aucun brouillon.</p>

  return (
    <section>
      <header className="mb-5">
        <h2 className="text-xl font-bold">Rapprochement commandé / livré / facturé</h2>
        <p className="text-sm text-slate-500">On ne facture pas ce qui n'est pas livré, sauf décision humaine tracée.</p>
      </header>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr><th className="p-3">Ligne</th><th className="p-3">Commandé</th><th className="p-3">Livré</th><th className="p-3">Facturé</th><th className="p-3">Écart</th><th className="p-3">Décision</th></tr>
          </thead>
          <tbody>
            {draft.lines.map((line) => {
              const mismatch = line.delivered < line.quantity
              return (
                <tr key={line.id} className={`border-t border-slate-100 ${mismatch ? 'bg-red-50' : ''}`}>
                  <td className="p-3 font-medium">{line.description}</td>
                  <td className="p-3">{line.quantity}</td>
                  <td className="p-3">{line.delivered}</td>
                  <td className="p-3">{money(line.line_total_ht)}</td>
                  <td className={`p-3 font-semibold ${mismatch ? 'text-red-700' : 'text-emerald-700'}`}>
                    {mismatch ? `−${line.quantity - line.delivered}` : 'ok'}
                  </td>
                  <td className="p-3">
                    {mismatch ? (
                      <div className="flex flex-wrap gap-1">
                        {['exclure', 'réduire', 'justificatif'].map((choice) => (
                          <button
                            key={choice}
                            onClick={() => decide(line, choice)}
                            className={`rounded border px-2 py-1 text-[11px] ${decisions[line.id] === choice ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-300 bg-white hover:bg-slate-100'}`}
                          >
                            {choice}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${statusColor('RESOLUE')}`}>conforme</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-slate-500">
        Anomalies ouvertes : {data.anomalies.filter((a) => a.status === 'OUVERTE').length} · résolues : {data.anomalies.filter((a) => a.status === 'RESOLUE').length}
      </p>
    </section>
  )
}
