import { money } from '../utils.js'

export default function Preview({ draft, invoice, go }) {
  const totals = draft?.recalculated_totals
  const printed = draft?.printed_totals
  const ecart = draft?.ecart
  const reference = invoice?.numero || draft?.numero_previsionnel || 'FAC-2026-00042'

  return (
    <section>
      <header className="mb-5">
        <h2 className="text-xl font-bold">Aperçu de la facture</h2>
        <p className="text-sm text-slate-500">Extrait, recalculé et écart affichés côte à côte. QR et code MECeF factices.</p>
      </header>

      <div className="grid gap-5 lg:grid-cols-[2fr_1fr]">
        <div className="rounded-lg border border-slate-200 bg-white p-6">
          <div className="flex items-start justify-between border-b border-slate-200 pb-4">
            <div>
              <p className="text-xs uppercase tracking-widest text-slate-500">Facture (simulation)</p>
              <h3 className="text-2xl font-black">{reference}</h3>
              <p className="mt-1 text-sm text-slate-600">{draft?.client?.name || 'Client'}</p>
            </div>
            <div className="h-20 w-20 border-2 border-dashed border-slate-300 p-2 text-center text-[9px] text-slate-400">
              QR<br />SIMULÉ<br />MECeF factice
            </div>
          </div>

          <table className="mt-4 w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-500"><tr><th className="py-2">Désignation</th><th className="py-2">Qté</th><th className="py-2 text-right">Total HT</th></tr></thead>
            <tbody>
              {(draft?.lines || []).map((line) => (
                <tr key={line.id} className="border-t border-slate-100">
                  <td className="py-2">{line.description}</td>
                  <td className="py-2">{line.quantity}</td>
                  <td className="py-2 text-right">{money(line.line_total_ht)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="mt-4 border-t border-slate-200 pt-4 text-sm">
            <div className="flex justify-between"><span>Total HT</span><strong>{money(totals?.ht)}</strong></div>
            <div className="flex justify-between"><span>TVA 18 %</span><strong>{money(totals?.vat)}</strong></div>
            <div className="flex justify-between text-lg"><span>Total TTC</span><strong>{money(totals?.ttc)}</strong></div>
          </div>
          <p className="mt-4 text-[11px] text-slate-500">Mentions obligatoires à compléter avant validation réelle. Prototype non agréé.</p>
        </div>

        <div className="space-y-3">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="text-xs uppercase text-slate-500">Imprimé sur la pièce</p>
            <p className="text-lg font-bold">{money(printed?.ht)}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="text-xs uppercase text-slate-500">Recalculé par le moteur</p>
            <p className="text-lg font-bold">{money(totals?.ht)}</p>
          </div>
          <div className="rounded-lg border border-red-300 bg-red-50 p-4">
            <p className="text-xs uppercase text-red-600">Écart</p>
            <p className="text-lg font-bold text-red-800">{money(ecart?.ht)}</p>
          </div>
          <button onClick={() => go('validation')} className="w-full rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">
            Passer à la validation →
          </button>
        </div>
      </div>
    </section>
  )
}
