import { api, USE_MOCK } from '../api.js'

export default function Audit({ data, run, setNotice }) {
  const verify = () => run(async () => {
    const result = await api.verifyAudit()
    setNotice({
      type: result.valid ? 'success' : 'error',
      text: `${result.detail} · ${result.events} événement(s) vérifié(s).`,
    })
  })

  const exportCsv = async () => {
    if (!USE_MOCK) {
      try {
        await api.downloadAuditCsv()
        setNotice({ type: 'success', text: 'Journal d’audit exporté en CSV.' })
      } catch (error) {
        setNotice({ type: 'error', text: error.message || String(error) })
      }
      return
    }
    const header = 'id,horodatage,action,acteur,cible,hash'
    const rows = data.audit.map((e) =>
      [e.id, e.at, e.action, e.actor, e.target || '', e.hash]
        .map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`)
        .join(',')
    )
    const blob = new Blob([[header, ...rows].join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'wema-audit.csv'
    a.click()
    URL.revokeObjectURL(url)
    setNotice({ type: 'success', text: 'Journal d’audit exporté en CSV.' })
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 shadow-sm">
        <div>
          <h2 className="text-base font-extrabold text-emerald-950">Journal d’intégrité SHA-256</h2>
          <p className="text-xs text-emerald-800">
            {data.audit.length} action(s) horodatée(s) et chaînée(s) : toute modification passée casse la chaîne.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={exportCsv}
            className="rounded-xl border border-emerald-300 bg-white px-3.5 py-2 text-xs font-bold text-emerald-900 hover:bg-emerald-100/50"
          >
            Exporter CSV
          </button>
          <button
            type="button"
            onClick={verify}
            className="rounded-xl bg-emerald-600 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-emerald-700"
          >
            Vérifier la chaîne
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="p-3.5">Horodatage</th>
              <th className="p-3.5">Action</th>
              <th className="p-3.5">Acteur</th>
              <th className="p-3.5">Cible</th>
              <th className="p-3.5">Empreinte</th>
            </tr>
          </thead>
          <tbody>
            {data.audit.slice(0, 50).map((event) => (
              <tr key={event.id} className="border-t border-slate-100 hover:bg-slate-50/70">
                <td className="p-3.5 font-mono text-xs text-slate-500">{event.at}</td>
                <td className="p-3.5 font-semibold text-slate-900">{event.action}</td>
                <td className="p-3.5 text-slate-700">{event.actor}</td>
                <td className="p-3.5 text-slate-600">{event.target || '—'}</td>
                <td className="p-3.5 font-mono text-xs text-slate-400">{String(event.hash || '').slice(0, 14)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
