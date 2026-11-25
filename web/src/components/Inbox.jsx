import { useState } from 'react'
import { api } from '../api.js'
import { statusColor } from '../utils.js'

export default function Inbox({ data, run, onOpen }) {
  const [dragging, setDragging] = useState(false)
  const waiting = data.documents.filter((d) => d.status === 'EN_ATTENTE_IA').length

  const importDemo = () => run(async () => {
    await api.extract('doc-041')
    onOpen('doc-041')
  })

  return (
    <section>
      <header className="mb-5">
        <h2 className="text-xl font-bold">Boîte d'entrée</h2>
        <p className="text-sm text-slate-500">Une pièce entre — devis PDF, photo ou message —, une facture juste sort.</p>
      </header>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); importDemo() }}
        className={`mb-6 rounded-lg border-2 border-dashed p-8 text-center transition ${dragging ? 'border-amber-500 bg-amber-50' : 'border-slate-300 bg-white'}`}
      >
        <p className="text-sm font-medium">Glisser une pièce ici</p>
        <p className="mt-1 text-xs text-slate-500">Mode démo : le devis témoin <code>DEV-2026-041</code> est utilisé.</p>
        <button onClick={importDemo} className="mt-4 rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">
          Importer et analyser le devis témoin
        </button>
      </div>

      {waiting > 0 && (
        <div className="mb-4 rounded border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {waiting} pièce{waiting > 1 ? 's' : ''} en file <strong>EN_ATTENTE_IA</strong> — reprise possible même si le service IA est coupé.
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr><th className="p-3">Pièce</th><th className="p-3">Type</th><th className="p-3">État</th><th className="p-3">Empreinte</th><th /></tr>
          </thead>
          <tbody>
            {data.documents.map((doc) => (
              <tr key={doc.id} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="p-3 font-medium">{doc.reference}</td>
                <td className="p-3 text-slate-500">{doc.type}</td>
                <td className="p-3"><span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${statusColor(doc.status)}`}>{doc.status}</span></td>
                <td className="p-3 font-mono text-xs text-slate-500">{doc.hash}</td>
                <td className="p-3 text-right">
                  <button onClick={() => onOpen(doc.id)} className="text-sm font-medium text-blue-700 hover:underline">Ouvrir →</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
