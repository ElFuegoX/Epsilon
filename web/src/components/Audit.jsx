import { api } from '../api.js'

export default function Audit({ data, run, setNotice }) {
  const verify = () => run(async () => {
    const result = await api.verifyAudit()
    setNotice(`${result.detail} · ${result.events} événement(s) vérifié(s).`)
  })

  return (
    <section>
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Journal d'audit</h2>
          <p className="text-sm text-slate-500">Chaque action est horodatée et chaînée par empreinte SHA-256.</p>
        </div>
        <button onClick={verify} className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">
          Vérifier la chaîne
        </button>
      </header>

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr><th className="p-3">Horodatage</th><th className="p-3">Action</th><th className="p-3">Acteur</th><th className="p-3">Cible</th><th className="p-3">Empreinte</th></tr>
          </thead>
          <tbody>
            {data.audit.map((event) => (
              <tr key={event.id} className="border-t border-slate-100">
                <td className="p-3 font-mono text-xs text-slate-500">{event.at}</td>
                <td className="p-3 font-medium">{event.action}</td>
                <td className="p-3">{event.actor}</td>
                <td className="p-3">{event.target}</td>
                <td className="p-3 font-mono text-xs text-slate-500">{event.hash}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-slate-500">Export CSV et vérification hors ligne : TODO côté Melon (`make verify`).</p>
    </section>
  )
}
