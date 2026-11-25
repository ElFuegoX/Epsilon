import { api } from '../api.js'
import { money } from '../utils.js'

export default function Lines({ draft, highlight, setHighlight, run, go }) {
  if (!draft) return <p className="text-sm text-slate-500">Aucun brouillon.</p>

  const update = (line, patch) => run(() => api.patchLine(line.id, patch))

  return (
    <section>
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Lignes du brouillon</h2>
          <p className="text-sm text-slate-500">Cliquez sur un prix pour voir sa source. Toute correction est tracée.</p>
        </div>
        <button onClick={() => go('controls')} className="rounded border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-100">
          Voir les contrôles →
        </button>
      </header>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="p-3">N°</th><th className="p-3">Désignation</th><th className="p-3">Qté</th>
              <th className="p-3">PU HT</th><th className="p-3">TVA</th><th className="p-3">Total HT</th>
            </tr>
          </thead>
          <tbody>
            {draft.lines.map((line) => (
              <tr key={line.id} className="border-t border-slate-100">
                <td className="p-3 text-slate-500">{line.line_no}</td>
                <td className="p-3 font-medium">{line.description}</td>
                <td className="p-3">
                  <input
                    type="number" min="0" value={line.quantity}
                    onChange={(e) => update(line, { quantity: Number(e.target.value) })}
                    className="w-16 rounded border border-slate-300 px-2 py-1"
                  />
                </td>
                <td className="p-3">
                  <button
                    onClick={() => setHighlight(line.field)}
                    className={`rounded px-2 py-1 ${highlight === line.field ? 'bg-amber-200 text-amber-950' : 'hover:bg-amber-50'}`}
                    title="Voir la source"
                  >
                    {money(line.unit_price_ht)}
                  </button>
                </td>
                <td className="p-3 text-slate-500">{line.tax_rate} %</td>
                <td className="p-3 font-semibold">{money(line.line_total_ht)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot className="bg-slate-50 font-semibold">
            <tr>
              <td className="p-3" colSpan="5">Total HT recalculé</td>
              <td className="p-3">{money(draft.recalculated_totals.ht)}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="text-xs uppercase text-slate-500">Imprimé</p>
          <p className="text-lg font-bold">{money(draft.printed_totals.ht)}</p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="text-xs uppercase text-slate-500">Recalculé</p>
          <p className="text-lg font-bold">{money(draft.recalculated_totals.ht)}</p>
        </div>
        <div className="rounded-lg border border-red-300 bg-red-50 p-4">
          <p className="text-xs uppercase text-red-600">Écart à expliquer</p>
          <p className="text-lg font-bold text-red-800">{money(draft.ecart.ht)}</p>
        </div>
      </div>
    </section>
  )
}
