import { money } from '../utils.js'

export default function Referentials({ data }) {
  return (
    <section>
      <header className="mb-5">
        <h2 className="text-xl font-bold">Référentiels</h2>
        <p className="text-sm text-slate-500">Clients / IFU, articles et tarifs, séries de numérotation. Données fictives.</p>
      </header>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <h3 className="border-b border-slate-100 p-4 text-sm font-bold">Clients</h3>
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">Nom</th><th className="p-3">IFU</th></tr></thead>
            <tbody>
              {data.clients.map((client) => (
                <tr key={client.id} className="border-t border-slate-100">
                  <td className="p-3">{client.name}</td>
                  <td className="p-3">{client.ifu || <span className="text-red-700">absent</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <h3 className="border-b border-slate-100 p-4 text-sm font-bold">Articles et tarifs</h3>
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">Désignation</th><th className="p-3">Prix HT</th></tr></thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.id} className="border-t border-slate-100">
                  <td className="p-3">{item.name}</td>
                  <td className="p-3">{money(item.price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="mt-5 rounded-lg border border-slate-200 bg-white p-4 text-sm">
        <h3 className="text-sm font-bold">Séries</h3>
        <p className="mt-2 text-slate-600">Factures : <code>FAC-AAAA-00000</code> · Avoirs : <code>AV-AAAA-00000</code></p>
        <p className="mt-1 text-xs text-slate-500">La numérotation se fait à la validation, dans une transaction. Aucun numéro n'est consommé en cas d'échec.</p>
      </div>
    </section>
  )
}
