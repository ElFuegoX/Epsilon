import { api, USE_MOCK } from '../api.js'
import { money, statusColor } from '../utils.js'

export default function Register({ data, role, run, setNotice }) {
  const canCredit = role === 'dirigeant'
  const canIssue = role === 'dirigeant' || role === 'assistante'

  const credit = (invoice) => run(async () => {
    const note = await api.creditNote(invoice.id, { total: true, motif: 'avoir total' })
    setNotice({ type: 'success', text: `Avoir ${note.numero} lié à ${invoice.numero}. La facture initiale reste inchangée.` })
  })

  const downloadPdf = (invoice) => {
    if (USE_MOCK) {
      setNotice({ type: 'info', text: 'Téléchargement PDF disponible dès que l’interface est connectée à l’API réelle.' })
      return
    }
    run(() => api.downloadInvoicePdf(invoice.id, invoice.numero))
  }

  return (
    <section>
      <header className="mb-5">
        <h2 className="text-xl font-bold">Registre</h2>
        <p className="text-sm text-slate-500">Brouillons, factures et avoirs. Une correction se fait par avoir lié, jamais par modification.</p>
      </header>

      <h3 className="mb-2 text-sm font-bold">Factures</h3>
      {data.invoices.length === 0 ? (
        <p className="mb-6 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">Aucune facture validée pour l'instant.</p>
      ) : (
        <div className="mb-6 space-y-3">
          {data.invoices.map((invoice) => {
            const clientLabel = invoice.client?.name || invoice.client || 'Client'
            const ttc = invoice.totals?.ttc ?? invoice.total_ttc
            return (
              <article key={invoice.id} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-mono font-bold">{invoice.numero}</p>
                    <p className="text-sm text-slate-600">{clientLabel} · {money(ttc)}</p>
                  </div>
                  <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${statusColor(invoice.status)}`}>{invoice.status}</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => downloadPdf(invoice)}
                    className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white hover:bg-slate-700"
                  >
                    Télécharger PDF
                  </button>
                  <button
                    type="button"
                    disabled={!canIssue}
                    title={canIssue ? '' : 'Action interdite en lecture seule'}
                    onClick={() => run(() => api.issue(invoice.id, 'email'))}
                    className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Émettre (simulation)
                  </button>
                  <button
                    type="button"
                    disabled={!canCredit}
                    title={canCredit ? '' : 'Réservé au Responsable comptable / Dirigeant'}
                    onClick={() => credit(invoice)}
                    className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Avoir total {!canCredit ? '(Comptable / Dirigeant)' : ''}
                  </button>
                </div>
                {(invoice.credit_notes || []).length > 0 && (
                  <p className="mt-2 text-xs text-emerald-700">Avoirs liés : {invoice.credit_notes.map((n) => n.numero).join(', ')}</p>
                )}
              </article>
            )
          })}
        </div>
      )}

      <h3 className="mb-2 text-sm font-bold">Brouillons</h3>
      <div className="space-y-2">
        {data.drafts.map((draft) => (
          <div key={draft.id} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white p-4 text-sm">
            <span>
              <strong>{draft.reference || draft.id}</strong> · {draft.client?.name || draft.client_detail?.raison_sociale || '— absent de la pièce —'}
            </span>
            <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${statusColor(draft.status)}`}>{draft.status}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
