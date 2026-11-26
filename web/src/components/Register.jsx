import { api, USE_MOCK } from '../api.js'
import { money, statusColor } from '../utils.js'

export default function Register({ data, role, run, setNotice }) {
  const canCredit = role === 'dirigeant'
  const canIssue = role === 'dirigeant' || role === 'assistante'

  const credit = (invoice) => run(async () => {
    const note = await api.creditNote(invoice.id, { total: true, motif: 'avoir total' })
    setNotice({ type: 'success', text: `Avoir ${note.numero} lié à ${invoice.numero}. La facture initiale reste inchangée.` })
  })

  const downloadPdf = async (invoice) => {
    if (USE_MOCK) {
      setNotice({ type: 'info', text: 'Téléchargement PDF disponible dès que l’interface est connectée à l’API réelle.' })
      return
    }
    try {
      await api.downloadInvoicePdf(invoice.id, invoice.numero)
      setNotice({ type: 'success', text: `PDF ${invoice.numero}.pdf téléchargé.` })
    } catch (error) {
      setNotice({ type: 'error', text: error.message || String(error) })
    }
  }

  return (
    <section className="space-y-5">
      <header>
        <h2 className="text-lg font-extrabold text-slate-900">Registre des factures & avoirs</h2>
        <p className="text-xs text-slate-500">Une facture validée est immuable : toute correction se fait par avoir lié.</p>
      </header>

      <div className="space-y-3">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
          Factures émises ({data.invoices.length})
        </h3>
        {data.invoices.length === 0 ? (
          <p className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-500 shadow-sm">
            Aucune facture validée pour l’instant.
          </p>
        ) : (
          <div className="space-y-2.5">
            {data.invoices.slice(0, 20).map((invoice) => {
              const clientLabel = invoice.client?.name || invoice.client || 'Client'
              const ttc = invoice.totals?.ttc ?? invoice.total_ttc
              return (
                <article key={invoice.id} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-mono text-sm font-black text-slate-900">{invoice.numero}</p>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {clientLabel} · <strong className="text-slate-900 tabular-nums">{money(ttc)}</strong>
                      </p>
                    </div>
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${statusColor(invoice.status)}`}>
                      {invoice.status}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => downloadPdf(invoice)}
                      className="rounded-xl bg-emerald-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-emerald-700"
                    >
                      Télécharger PDF
                    </button>
                    <button
                      type="button"
                      disabled={!canIssue}
                      title={canIssue ? '' : 'Action interdite en lecture seule'}
                      onClick={() => run(() => api.issue(invoice.id, 'whatsapp'))}
                      className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Émettre WhatsApp
                    </button>
                    <button
                      type="button"
                      disabled={!canCredit}
                      title={canCredit ? '' : 'Réservé au Responsable comptable / Dirigeant'}
                      onClick={() => credit(invoice)}
                      className="rounded-xl border border-red-200 bg-white px-3 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Avoir total {!canCredit ? '(Comptable / Dirigeant)' : ''}
                    </button>
                  </div>
                  {(invoice.credit_notes || []).length > 0 && (
                    <p className="mt-2.5 rounded-xl bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-800">
                      Avoirs liés : {invoice.credit_notes.map((n) => n.numero).join(', ')}
                    </p>
                  )}
                </article>
              )
            })}
          </div>
        )}
      </div>

      <div className="space-y-2.5">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
          Brouillons en préparation ({data.drafts.length})
        </h3>
        {data.drafts.slice(0, 10).map((draft) => (
          <div key={draft.id} className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white p-4 text-sm shadow-sm">
            <div>
              <span className="font-bold text-slate-900">{draft.reference || draft.id}</span>
              <span className="ml-2 text-xs text-slate-500">
                {draft.client?.name || draft.client_detail?.raison_sociale || '— absent de la pièce —'}
              </span>
            </div>
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${statusColor(draft.status)}`}>
              {draft.status}
            </span>
          </div>
        ))}
      </div>
    </section>
  )
}
