import { api, USE_MOCK } from '../api.js'

export default function Audit({ data, run, setNotice }) {
  const verify = () => run(async () => {
    const result = await api.verifyAudit()
    setNotice({
      type: result.valid ? 'success' : 'error',
      text: `${result.detail} · ${result.events} événement(s) vérifié(s).`,
    })
  })

  const exportCsv = () => {
    if (!USE_MOCK) {
      run(() => api.downloadAuditCsv())
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
    <section>
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Journal d'audit</h2>
          <p className="text-sm text-slate-500">Chaque action est horodatée et chaînée par empreinte SHA-256.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={exportCsv}
            className="rounded border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-100"
          >
            Exporter CSV
          </button>
          <button
            type="button"
            onClick={verify}
            className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            Vérifier la chaîne
          </button>
        </div>
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
                <td className="p-3">{event.target || '—'}</td>
                <td className="p-3 font-mono text-xs text-slate-500">{String(event.hash || '').slice(0, 14)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-slate-500">Vérification hors ligne disponible aussi via <code>python -m cli verify</code> (chaîne SHA-256, numérotation et hash PDF).</p>
    </section>
  )
}
