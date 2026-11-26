import { useState } from 'react'
import { api, USE_MOCK } from '../api.js'
import { money, statusColor } from '../utils.js'

export default function Validation({ draft, invoice, role, data, run, setNotice, go }) {
  const [submitting, setSubmitting] = useState(false)
  const openAnomalies = data.anomalies.filter((a) => a.status === 'OUVERTE').length
  const canValidate = role === 'dirigeant'

  const validate = async () => {
    if (submitting || invoice || !canValidate || !draft?.id) return
    setSubmitting(true)
    await run(async () => {
      const created = await api.validate(draft.id)
      setNotice({ type: 'success', text: `Facture ${created.numero} validée et numérotée.` })
    })
    setSubmitting(false)
  }

  const downloadPdf = async () => {
    if (!invoice?.id) return
    if (USE_MOCK) {
      setNotice({ type: 'info', text: 'Téléchargement PDF disponible dès que l’interface est connectée à l’API réelle.' })
      return
    }
    try {
      await api.downloadInvoicePdf(invoice.id, invoice.numero)
      setNotice({ type: 'success', text: `PDF ${invoice.numero}.pdf téléchargé.` })
    } catch (error) {
      setNotice({ type: 'error', text: error.message || String(error) })
    }
  }

  return (
    <section className="space-y-5">
      <header>
        <h2 className="text-lg font-extrabold text-slate-900">Validation Double Clé</h2>
        <p className="text-xs text-slate-500">Le numéro fiscal est attribué en une seule transaction protégée contre le double-clic.</p>
      </header>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Carte récapitulative */}
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <h3 className="text-sm font-bold text-slate-900">Récapitulatif du dossier</h3>
            <span className="rounded-lg bg-slate-100 px-2.5 py-1 font-mono text-xs font-bold text-slate-700">
              {draft?.numero_previsionnel || '—'}
            </span>
          </div>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Client</dt>
              <dd className="font-semibold text-slate-900">{draft?.client?.name || draft?.client_detail?.raison_sociale || '— absent —'}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">IFU</dt>
              <dd className={draft?.client?.ifu || draft?.client_detail?.ifu ? 'font-mono font-semibold text-slate-900' : 'font-semibold text-red-700'}>
                {draft?.client?.ifu || draft?.client_detail?.ifu || 'absent de la pièce'}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Total TTC recalculé</dt>
              <dd className="text-base font-black text-slate-900 tabular-nums">{money(draft?.recalculated_totals?.ttc)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Anomalies ouvertes</dt>
              <dd className={openAnomalies ? 'font-bold text-red-700' : 'font-bold text-emerald-700'}>{openAnomalies}</dd>
            </div>
          </dl>
        </div>

        {/* Carte d'engagement fintech */}
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-bold text-slate-900">Engagement</h3>
          {invoice ? (
            <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-5 text-center">
              <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-emerald-600 text-lg font-black text-white shadow-sm">
                ✓
              </div>
              <p className="mt-2 font-mono text-base font-black text-emerald-950">{invoice.numero}</p>
              <p className="text-xs font-medium text-emerald-800">
                Facture figée · <span className={`rounded-full px-2 py-0.5 font-bold ${statusColor(invoice.status)}`}>{invoice.status}</span>
              </p>
              <p className="mt-1 text-xs text-emerald-700">Protégée contre toute modification (409). Toute correction passe par un avoir lié.</p>

              <div className="mt-4 grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={downloadPdf}
                  className="rounded-xl bg-emerald-600 px-3 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-emerald-700"
                >
                  Télécharger PDF
                </button>
                <button
                  type="button"
                  onClick={() => go('register')}
                  className="rounded-xl bg-slate-900 px-3 py-2.5 text-xs font-bold text-white hover:bg-slate-800"
                >
                  Voir le registre
                </button>
                {role !== 'lecture' && (
                  <>
                    <button
                      type="button"
                      onClick={() => run(() => api.issue(invoice.id, 'whatsapp'))}
                      className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50"
                    >
                      Envoyer WhatsApp
                    </button>
                    <button
                      type="button"
                      onClick={() => run(() => api.issue(invoice.id, 'email'))}
                      className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50"
                    >
                      Envoyer Email
                    </button>
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="mt-4 space-y-3">
              {!canValidate && (
                <p className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950">
                  Accès verrouillé pour ce poste : seul le <strong>Responsable comptable / Dirigeant</strong> peut valider et attribuer un numéro fiscal.
                </p>
              )}
              {openAnomalies > 0 && (
                <p className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800">
                  {openAnomalies} anomalie(s) ouverte(s). Traitez-les dans l’écran <strong>Anomalies à traiter</strong> avant la validation définitive.
                </p>
              )}
              <button
                type="button"
                onClick={validate}
                disabled={submitting || !canValidate || !draft?.id}
                className="w-full rounded-2xl bg-emerald-600 px-4 py-3.5 text-sm font-extrabold text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {!canValidate
                  ? 'Réservé au Responsable comptable / Dirigeant'
                  : submitting
                    ? 'Validation en cours…'
                    : 'Approuver & Numéroter la facture'}
              </button>
              <p className="text-center text-[11px] text-slate-500">
                Bouton désactivé dès le premier clic : un double clic ne crée jamais de doublon.
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
