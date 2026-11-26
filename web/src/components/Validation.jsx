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

  const downloadPdf = () => {
    if (!invoice?.id) return
    if (USE_MOCK) {
      setNotice({ type: 'info', text: 'Téléchargement PDF disponible dès que l’interface est connectée à l’API réelle.' })
      return
    }
    run(() => api.downloadInvoicePdf(invoice.id, invoice.numero))
  }

  return (
    <section>
      <header className="mb-5">
        <h2 className="text-xl font-bold">Validation et numérotation</h2>
        <p className="text-sm text-slate-500">Le numéro est un acte, pas un compteur. Double confirmation côté front et idempotence côté API.</p>
      </header>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h3 className="text-sm font-bold">Récapitulatif</h3>
          <dl className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Client</dt>
              <dd>{draft?.client?.name || draft?.client_detail?.raison_sociale || '— absent de la pièce —'}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">IFU</dt>
              <dd className={draft?.client?.ifu || draft?.client_detail?.ifu ? 'font-mono text-slate-900' : 'text-red-700'}>
                {draft?.client?.ifu || draft?.client_detail?.ifu || 'absent de la pièce'}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Total TTC</dt>
              <dd className="font-bold">{money(draft?.recalculated_totals?.ttc)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Anomalies ouvertes</dt>
              <dd className={openAnomalies ? 'font-bold text-red-700' : 'text-emerald-700'}>{openAnomalies}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Numéro prévisionnel</dt>
              <dd className="font-mono">{draft?.numero_previsionnel || '—'}</dd>
            </div>
          </dl>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h3 className="text-sm font-bold">Engagement</h3>
          {invoice ? (
            <div className="mt-4 rounded border border-emerald-300 bg-emerald-50 p-4">
              <p className="text-sm font-semibold text-emerald-900">{invoice.numero} · {invoice.status}</p>
              <p className="mt-1 text-xs text-emerald-800">Snapshot figé. Une facture émise ne peut plus être modifiée (409).</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={downloadPdf}
                  className="rounded bg-emerald-700 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-800"
                >
                  Télécharger le PDF
                </button>
                <button
                  type="button"
                  onClick={() => go('register')}
                  className="rounded bg-slate-900 px-3 py-2 text-xs font-medium text-white hover:bg-slate-700"
                >
                  Voir le registre
                </button>
                {role !== 'lecture' && (
                  <>
                    <button
                      type="button"
                      onClick={() => run(() => api.issue(invoice.id, 'email'))}
                      className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-medium hover:bg-slate-50"
                    >
                      Émettre (email)
                    </button>
                    <button
                      type="button"
                      onClick={() => run(() => api.issue(invoice.id, 'whatsapp'))}
                      className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-medium hover:bg-slate-50"
                    >
                      Émettre (WhatsApp)
                    </button>
                  </>
                )}
              </div>
            </div>
          ) : (
            <>
              {!canValidate && (
                <p className="mt-4 rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
                  Accès verrouillé pour ce poste : seul le <strong>Responsable comptable / Dirigeant</strong> peut valider et attribuer un numéro fiscal.
                </p>
              )}
              {openAnomalies > 0 && (
                <p className="mt-3 rounded border border-red-300 bg-red-50 p-3 text-xs text-red-800">
                  {openAnomalies} anomalie(s) ouverte(s). Résolvez-les dans l’onglet Contrôles avant la validation définitive.
                </p>
              )}
              <button
                type="button"
                onClick={validate}
                disabled={submitting || !canValidate || !draft?.id}
                className="mt-4 w-full rounded bg-slate-900 px-4 py-3 text-sm font-bold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {!canValidate
                  ? 'Réservé au Responsable comptable / Dirigeant'
                  : submitting
                    ? 'Validation en cours…'
                    : 'Valider et numéroter'}
              </button>
              <p className="mt-2 text-[11px] text-slate-500">Le bouton se désactive après le premier clic : un double clic ne crée qu’une seule facture.</p>
            </>
          )}
          {invoice && (
            <p className="mt-3 text-xs text-slate-500">
              État du registre : <span className={`rounded-full px-2 py-1 font-semibold ${statusColor(invoice.status)}`}>{invoice.status}</span>
            </p>
          )}
        </div>
      </div>
    </section>
  )
}
