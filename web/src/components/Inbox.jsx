import { useRef, useState } from 'react'
import { api } from '../api.js'
import { money, statusColor } from '../utils.js'

export default function Inbox({ data, run, onOpen }) {
  const [mode, setMode] = useState(null) // null | 'file' | 'text'
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
      setMode(null)
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
      setMode(null)
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
    <section className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-[1.05fr_1.25fr] lg:items-start">
        {/* Colonne gauche : Carte Hero Fintech + Capture terrain */}
        <div className="space-y-4">
          <div className="rounded-3xl bg-gradient-to-br from-emerald-600 via-emerald-700 to-teal-800 p-5 text-white shadow-md">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-emerald-100">
                Protection facturation
              </span>
              <button
                type="button"
                onClick={importDemo}
                disabled={busy}
                className="rounded-xl bg-white/15 px-3 py-1.5 text-xs font-bold text-white backdrop-blur transition hover:bg-white/25 disabled:opacity-50"
              >
                Tester DEV-2026-041 →
              </button>
            </div>
            <p className="mt-3 text-3xl font-black tracking-tight tabular-nums">
              {money(avoidedFcfa)}
            </p>
            <p className="mt-0.5 text-xs text-emerald-100">
              d’erreurs détectées et bloquées avant émission
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3 border-t border-white/20 pt-3.5 text-xs">
              <div>
                <span className="text-emerald-100/80">Dossiers analysés</span>
                <p className="mt-0.5 text-base font-extrabold tabular-nums">
                  {treated} <span className="text-xs font-normal text-emerald-100/80">/ {data.documents.length}</span>
                </p>
              </div>
              <div>
                <span className="text-emerald-100/80">Anomalies actives</span>
                <p className="mt-0.5 text-base font-extrabold tabular-nums">
                  {blockedAnomalies} à traiter
                </p>
              </div>
            </div>
          </div>

          {/* 2 gros boutons tactiles d'import terrain */}
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => setMode(mode === 'file' ? null : 'file')}
              className={`rounded-2xl border p-4 text-left shadow-sm transition ${
                mode === 'file'
                  ? 'border-emerald-600 bg-emerald-50 ring-2 ring-emerald-500/20'
                  : 'border-slate-200 bg-white hover:border-emerald-400'
              }`}
            >
              <p className="text-sm font-bold text-slate-900">Photo ou PDF</p>
              <p className="mt-0.5 text-xs text-slate-500">Devis, bon de commande</p>
            </button>
            <button
              type="button"
              onClick={() => setMode(mode === 'text' ? null : 'text')}
              className={`rounded-2xl border p-4 text-left shadow-sm transition ${
                mode === 'text'
                  ? 'border-emerald-600 bg-emerald-50 ring-2 ring-emerald-500/20'
                  : 'border-slate-200 bg-white hover:border-emerald-400'
              }`}
            >
              <p className="text-sm font-bold text-slate-900">Coller WhatsApp</p>
              <p className="mt-0.5 text-xs text-slate-500">Message client brut</p>
            </button>
          </div>

          {/* Tiroir Fichier */}
          {mode === 'file' && (
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
              className={`rounded-2xl border-2 border-dashed p-5 text-center transition ${
                dragging ? 'border-emerald-500 bg-emerald-50' : 'border-slate-300 bg-white'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.webp,.txt"
                onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                className="hidden"
                id="wema-file-input"
              />
              <p className="text-sm font-semibold text-slate-800">
                {selectedFile ? `Prêt : ${selectedFile.name}` : 'Glissez un devis PDF ou une photo ici'}
              </p>
              <p className="mt-1 text-xs text-slate-500">PDF, PNG, JPG, WebP, TXT (max 20 Mo)</p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                <label
                  htmlFor="wema-file-input"
                  className="cursor-pointer rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                >
                  Parcourir
                </label>
                <button
                  type="button"
                  disabled={!selectedFile || busy}
                  onClick={() => handleFileSubmit()}
                  className="rounded-xl bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  {busy ? 'Analyse…' : 'Importer et analyser'}
                </button>
              </div>
            </div>
          )}

          {/* Tiroir Message WhatsApp */}
          {mode === 'text' && (
            <form onSubmit={handleTextSubmit} className="space-y-3 rounded-2xl border border-emerald-200 bg-white p-4 shadow-sm">
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-700" htmlFor="msg-title">
                  Nom de la commande (optionnel)
                </label>
                <input
                  id="msg-title"
                  type="text"
                  value={msgTitle}
                  onChange={(e) => setMsgTitle(e.target.value)}
                  placeholder="Ex. Commande WhatsApp - Ets Sossa"
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm focus:border-emerald-500 focus:bg-white focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-700" htmlFor="msg-text">
                  Message brut du client
                </label>
                <textarea
                  id="msg-text"
                  rows={3}
                  value={msgText}
                  onChange={(e) => setMsgText(e.target.value)}
                  placeholder="Collez ici le message WhatsApp ou email reçu..."
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm focus:border-emerald-500 focus:bg-white focus:outline-none"
                />
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setMode(null)}
                  className="rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  disabled={!msgText.trim() || busy}
                  className="rounded-xl bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  {busy ? 'Analyse…' : 'Analyser ce message'}
                </button>
              </div>
            </form>
          )}

          {waiting > 0 && (
            <div className="rounded-2xl border border-amber-300 bg-amber-50 px-4 py-3 text-xs font-medium text-amber-950">
              <strong>{waiting} pièce{waiting > 1 ? 's' : ''} en file sécurisée</strong> — reprise automatique sans doublon dès que le traitement continue.
            </div>
          )}
        </div>

        {/* Colonne droite : File des dossiers en cartes empilées */}
        <div className="space-y-3">
          <div className="flex items-center justify-between px-1">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Dossiers récents ({data.documents.length})
            </h2>
            <span className="text-xs text-slate-400">Touchez un dossier pour le vérifier</span>
          </div>

          {data.documents.length === 0 ? (
            <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-400">
              Aucune pièce importée pour l’instant. Choisissez un fichier, collez un message WhatsApp ou testez DEV-2026-041.
            </div>
          ) : (
            <div className="space-y-2.5">
              {data.documents.slice(0, 12).map((doc) => {
                const isWaiting = doc.status === 'EN_ATTENTE_IA'
                return (
                  <button
                    key={doc.id}
                    type="button"
                    onClick={() => onOpen(doc.id)}
                    className={`w-full rounded-2xl border p-4 text-left shadow-sm transition hover:scale-[1.005] ${
                      isWaiting
                        ? 'border-amber-200 bg-amber-50/40 hover:border-amber-400'
                        : 'border-slate-200 bg-white hover:border-emerald-400'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-bold text-slate-900">
                          {doc.reference || doc.filename || doc.id}
                        </p>
                        <p className="mt-0.5 text-xs text-slate-500">
                          {doc.type} · empreinte <span className="font-mono">{String(doc.hash || '').slice(0, 8)}</span>
                        </p>
                      </div>
                      <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold ${statusColor(doc.status)}`}>
                        {doc.status}
                      </span>
                    </div>
                    <div className="mt-2.5 flex items-center justify-between text-xs">
                      <span className="text-slate-400">{doc.filename}</span>
                      <span className="font-bold text-emerald-700">Ouvrir →</span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
