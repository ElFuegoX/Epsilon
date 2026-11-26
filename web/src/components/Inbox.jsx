import { useRef, useState } from 'react'
import { api } from '../api.js'
import { money, statusColor } from '../utils.js'

export default function Inbox({ data, run, onOpen }) {
  const [mode, setMode] = useState('file')
  const [dragging, setDragging] = useState(false)
  const [selectedFile, setSelectedFile] = useState(null)
  const [msgTitle, setMsgTitle] = useState('')
  const [msgText, setMsgText] = useState('')
  const [busy, setBusy] = useState(false)
  const fileInputRef = useRef(null)

  const waiting = data.documents.filter((d) => d.status === 'EN_ATTENTE_IA').length
  const treated = data.documents.filter((d) => d.status === 'EXTRAIT').length
  const blockedAnomalies = data.anomalies.filter(
    (a) => a.status === 'OUVERTE' && (a.severity === 'BLOQUANTE' || a.severity === 'BLOQUANT')
  ).length
  const avoidedFcfa = data.drafts.reduce((sum, d) => {
    const ecartHt = Math.abs(Number(d?.ecart?.ht || 0))
    const ecartTtc = Math.abs(Number(d?.ecart?.ttc || 0))
    return sum + (ecartHt || ecartTtc)
  }, 0)

  const handleFileSubmit = async (fileToUpload) => {
    const target = fileToUpload || selectedFile
    if (!target || busy) return
    setBusy(true)
    await run(async () => {
      const created = await api.importFile(target)
      const extracted = await api.extract(created.id)
      setSelectedFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
      onOpen(created.id, extracted?.draft_id || null)
      return extracted
    })
    setBusy(false)
  }

  const handleTextSubmit = async (e) => {
    e.preventDefault()
    if (!msgText.trim() || busy) return
    setBusy(true)
    await run(async () => {
      const nom = msgTitle.trim() || `whatsapp_${Date.now()}.txt`
      const created = await api.importText({ nom, texte: msgText.trim(), type: 'message', canal: 'whatsapp_sim' })
      const extracted = await api.extract(created.id)
      setMsgTitle('')
      setMsgText('')
      onOpen(created.id, extracted?.draft_id || null)
      return extracted
    })
    setBusy(false)
  }

  const importDemo = async () => {
    if (busy) return
    setBusy(true)
    const demoDoc = data.documents.find((d) => d.reference === 'DEV-2026-041') || data.documents[0]
    await run(async () => {
      if (demoDoc) {
        const extracted = await api.extract(demoDoc.id)
        onOpen(demoDoc.id, extracted?.draft_id || null)
        return extracted
      }
      const created = await api.importText({
        nom: 'DEV-2026-041.txt',
        texte: 'Devis DEV-2026-041 — Ets Sossa Materiaux : 4 Banquettes x 185 000, 2 Tables basses x 120 000, 1 Livraison x 60 000.',
        type: 'devis',
        canal: 'demo',
      })
      const extracted = await api.extract(created.id)
      onOpen(created.id, extracted?.draft_id || null)
      return extracted
    })
    setBusy(false)
  }

  return (
    <section>
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold">Boîte d'entrée</h2>
          <p className="text-sm text-slate-500">Déposez un devis, une photo ou collez un message WhatsApp : WÉMA vérifie avant de facturer.</p>
        </div>
        <button
          type="button"
          onClick={importDemo}
          disabled={busy}
          className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-100 disabled:opacity-50"
        >
          Tester le devis témoin (DEV-2026-041)
        </button>
      </header>

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Pièces analysées</p>
          <p className="mt-1 text-2xl font-black text-slate-900">{treated} <span className="text-xs font-normal text-slate-400">/ {data.documents.length}</span></p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Pièges bloqués</p>
          <p className={`mt-1 text-2xl font-black ${blockedAnomalies > 0 ? 'text-red-700' : 'text-emerald-700'}`}>{blockedAnomalies}</p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Erreurs évitées</p>
          <p className="mt-1 text-2xl font-black text-emerald-700">{money(avoidedFcfa)}</p>
        </div>
      </div>

      <div className="mb-6 overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex border-b border-slate-200 bg-slate-50 text-xs font-semibold">
          <button
            type="button"
            onClick={() => setMode('file')}
            className={`px-4 py-3 transition ${mode === 'file' ? 'border-b-2 border-slate-900 bg-white text-slate-900' : 'text-slate-500 hover:text-slate-800'}`}
          >
            1. Choisir un fichier (PDF / Photo)
          </button>
          <button
            type="button"
            onClick={() => setMode('text')}
            className={`px-4 py-3 transition ${mode === 'text' ? 'border-b-2 border-slate-900 bg-white text-slate-900' : 'text-slate-500 hover:text-slate-800'}`}
          >
            2. Coller un message WhatsApp
          </button>
        </div>

        {mode === 'file' ? (
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              const dropped = e.dataTransfer?.files?.[0]
              if (dropped) {
                setSelectedFile(dropped)
                handleFileSubmit(dropped)
              }
            }}
            className={`p-6 text-center transition ${dragging ? 'bg-amber-50' : 'bg-white'}`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.webp,.txt"
              onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
              className="hidden"
              id="wema-file-input"
            />
            <p className="text-sm font-medium text-slate-800">
              {selectedFile ? `Fichier prêt : ${selectedFile.name}` : 'Glissez un devis PDF ou une photo de commande ici'}
            </p>
            <p className="mt-1 text-xs text-slate-500">Formats acceptés : PDF, PNG, JPG, WebP, TXT (max 20 Mo).</p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              <label
                htmlFor="wema-file-input"
                className="cursor-pointer rounded border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Parcourir mon ordinateur
              </label>
              <button
                type="button"
                disabled={!selectedFile || busy}
                onClick={() => handleFileSubmit()}
                className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {busy ? 'Analyse en cours…' : 'Importer et analyser'}
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleTextSubmit} className="space-y-3 p-5">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600" htmlFor="msg-title">
                Nom / référence de la commande (optionnel)
              </label>
              <input
                id="msg-title"
                type="text"
                value={msgTitle}
                onChange={(e) => setMsgTitle(e.target.value)}
                placeholder="Ex. Commande WhatsApp - Ets Sossa"
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600" htmlFor="msg-text">
                Message brut du client
              </label>
              <textarea
                id="msg-text"
                rows={4}
                value={msgText}
                onChange={(e) => setMsgText(e.target.value)}
                placeholder="Ex. Bonjour chef, envoie-moi 10 cartons d'eau 1,5L et 2 tables basses à livrer à Akpakpa..."
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={!msgText.trim() || busy}
                className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {busy ? 'Analyse en cours…' : 'Importer et analyser ce message'}
              </button>
            </div>
          </form>
        )}
      </div>

      {waiting > 0 && (
        <div className="mb-4 rounded border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {waiting} pièce{waiting > 1 ? 's' : ''} en file <strong>EN_ATTENTE_IA</strong> — reprise automatique sans doublon.
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr><th className="p-3">Pièce</th><th className="p-3">Type</th><th className="p-3">État</th><th className="p-3">Empreinte</th><th /></tr>
          </thead>
          <tbody>
            {data.documents.length === 0 ? (
              <tr>
                <td colSpan={5} className="p-6 text-center text-sm text-slate-400">
                  Aucune pièce importée pour l'instant. Déposez un fichier, collez un message ou testez le devis témoin.
                </td>
              </tr>
            ) : (
              data.documents.map((doc) => (
                <tr key={doc.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="p-3 font-medium">{doc.reference || doc.filename || doc.id}</td>
                  <td className="p-3 text-slate-500">{doc.type}</td>
                  <td className="p-3"><span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${statusColor(doc.status)}`}>{doc.status}</span></td>
                  <td className="p-3 font-mono text-xs text-slate-500">{String(doc.hash || '').slice(0, 10)}</td>
                  <td className="p-3 text-right">
                    <button onClick={() => onOpen(doc.id)} className="text-sm font-medium text-blue-700 hover:underline">Ouvrir →</button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
