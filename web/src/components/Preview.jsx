import { money } from '../utils.js'

export default function Preview({ draft, invoice, go }) {
  const totals = draft?.recalculated_totals
  const printed = draft?.printed_totals
  const ecart = draft?.ecart
  const reference = invoice?.numero || draft?.numero_previsionnel || 'FAC-2026-00061'

  return (
    <section className="space-y-5">
      <header>
        <h2 className="text-lg font-extrabold text-slate-900">Aperçu de la facture</h2>
        <p className="text-xs text-slate-500">Montant imprimé, montant recalculé et écart côte à côte. QR et code MECeF factices.</p>
      </header>

      <div className="grid gap-5 lg:grid-cols-[2fr_1fr]">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-start justify-between border-b border-slate-100 pb-4">
            <div>
              <p className="text-[11px] font-bold uppercase tracking-widest text-emerald-700">Facture (simulation)</p>
              <h3 className="mt-0.5 font-mono text-2xl font-black text-slate-900">{reference}</h3>
              <p className="mt-1 text-sm font-medium text-slate-600">{draft?.client?.name || 'Client'}</p>
            </div>
            <div className="flex h-20 w-20 items-center justify-center rounded-xl border-2 border-dashed border-slate-300 p-2 text-center text-[9px] font-bold text-slate-400">
              QR<br />SIMULÉ<br />MECeF
            </div>
          </div>

          <table className="mt-4 w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-400">
              <tr>
                <th className="py-2">Désignation</th>
                <th className="py-2">Qté</th>
                <th className="py-2 text-right">Total HT</th>
              </tr>
            </thead>
            <tbody>
              {(draft?.lines || []).map((line) => (
                <tr key={line.id} className="border-t border-slate-100">
                  <td className="py-2.5 font-medium text-slate-900">{line.description}</td>
                  <td className="py-2.5 tabular-nums text-slate-600">{line.quantity}</td>
                  <td className="py-2.5 text-right font-semibold tabular-nums">{money(line.line_total_ht)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="mt-4 space-y-1.5 border-t border-slate-200 pt-4 text-sm">
            <div className="flex justify-between text-slate-600"><span>Total HT</span><strong className="tabular-nums text-slate-900">{money(totals?.ht)}</strong></div>
            <div className="flex justify-between text-slate-600"><span>TVA 18 %</span><strong className="tabular-nums text-slate-900">{money(totals?.vat)}</strong></div>
            <div className="flex justify-between pt-1 text-lg font-black text-slate-900"><span>Total TTC</span><strong className="tabular-nums text-emerald-700">{money(totals?.ttc)}</strong></div>
          </div>
          <p className="mt-4 text-[11px] text-slate-400">Mentions obligatoires à compléter avant validation réelle. Prototype non agréé.</p>
        </div>

        <div className="space-y-3">
          <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-semibold uppercase text-slate-400">Imprimé sur la pièce</p>
            <p className="mt-1 text-lg font-black tabular-nums text-slate-900">{money(printed?.ht)}</p>
          </div>
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50/60 p-4 shadow-sm">
            <p className="text-xs font-semibold uppercase text-emerald-700">Recalculé exact</p>
            <p className="mt-1 text-lg font-black tabular-nums text-emerald-900">{money(totals?.ht)}</p>
          </div>
          <div className={`rounded-2xl border p-4 shadow-sm ${ecart?.ht ? 'border-red-200 bg-red-50' : 'border-slate-200 bg-white'}`}>
            <p className={`text-xs font-semibold uppercase ${ecart?.ht ? 'text-red-600' : 'text-slate-400'}`}>Écart détecté</p>
            <p className={`mt-1 text-lg font-black tabular-nums ${ecart?.ht ? 'text-red-800' : 'text-emerald-700'}`}>{money(ecart?.ht ?? 0)}</p>
          </div>
          <button
            type="button"
            onClick={() => go('validation')}
            className="w-full rounded-2xl bg-emerald-600 px-4 py-3 text-sm font-extrabold text-white shadow-sm hover:bg-emerald-700"
          >
            Passer à la validation →
          </button>
        </div>
      </div>
    </section>
  )
}
