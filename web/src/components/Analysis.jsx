import SourceViewer from './SourceViewer'
import { api } from '../api.js'
import { money } from '../utils.js'

const LABELS = {
  reference: 'Référence',
  date: 'Date',
  client_name: 'Client',
  client_ifu: 'IFU',
  line_1_price: 'Ligne 1 · prix unitaire',
  line_2_price: 'Ligne 2 · prix unitaire',
  line_3_price: 'Ligne 3 · prix unitaire',
  printed_ht: 'Total HT imprimé',
}

export default function Analysis({ document: doc, draft, highlight, setHighlight, run, setNotice, go }) {
  const copyClarification = async () => {
    await run(async () => {
      const { message } = await api.clarificationMessage(draft.id)
      try { await navigator.clipboard.writeText(message) } catch { /* presse-papiers indisponible */ }
      setNotice(`Message prêt à copier : ${message}`)
    })
  }

  return (
    <section>
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Analyse · provenance des champs</h2>
          <p className="text-sm text-slate-500">Cliquez sur un champ pour surligner sa source. Aucune valeur n'est devinée.</p>
        </div>
        <button onClick={() => go('lines')} className="rounded border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-100">
          Voir les lignes →
        </button>
      </header>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <SourceViewer document={doc} highlight={highlight} onSelectField={setHighlight} />
        </div>

        <div className="space-y-4">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <h3 className="mb-3 text-sm font-bold">En-tête extrait</h3>
            <dl className="divide-y divide-slate-100 text-sm">
              {Object.entries(LABELS).map(([key, label]) => {
                const field = doc?.fields?.[key]
                const absent = !field || field.value == null
                return (
                  <div key={key} className="flex items-center justify-between gap-3 py-2">
                    <dt className="text-slate-600">{label}</dt>
                    <dd className="text-right">
                      {absent ? (
                        <span className="rounded bg-red-50 px-2 py-1 text-xs font-medium text-red-700">— absent de la pièce —</span>
                      ) : (
                        <button
                          onClick={() => setHighlight(key)}
                          className={`rounded px-2 py-1 font-medium hover:bg-amber-100 ${highlight === key ? 'bg-amber-200 text-amber-950' : 'text-slate-900'}`}
                        >
                          {typeof field.value === 'number' && key !== 'reference' ? money(field.value) : field.value}
                          <span className="ml-2 text-[10px] text-slate-400">p.{field.page}</span>
                        </button>
                      )}
                    </dd>
                  </div>
                )
              })}
            </dl>
          </div>

          {doc?.fields?.client_ifu?.motif === 'ABSENT_DE_LA_PIECE' && (
            <div className="rounded-lg border border-red-300 bg-red-50 p-4">
              <p className="text-sm font-semibold text-red-800">Champ obligatoire manquant : IFU</p>
              <p className="mt-1 text-xs text-red-700">Le système ne devine pas : il demande la donnée à la source.</p>
              <button onClick={copyClarification} className="mt-3 rounded bg-red-700 px-3 py-2 text-xs font-medium text-white hover:bg-red-800">
                Copier le message de clarification
              </button>
            </div>
          )}

          {draft && (
            <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
              <h3 className="mb-2 text-sm font-bold">Brouillon lié</h3>
              <p><span className="text-slate-500">Référence :</span> {draft.reference}</p>
              <p><span className="text-slate-500">Client :</span> {draft.client.name}</p>
              <p><span className="text-slate-500">Lignes :</span> {draft.lines.length}</p>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
