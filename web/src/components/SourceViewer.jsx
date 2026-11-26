import { useEffect, useRef, useState } from 'react'
import { API_URL, getRole } from '../api.js'
import { money } from '../utils.js'

const LABELS = {
  reference: 'Référence',
  date: 'Date',
  client_name: 'Client',
  client_ifu: 'IFU',
  line_1_price: 'Ligne 1 · PU',
  line_2_price: 'Ligne 2 · PU',
  line_3_price: 'Ligne 3 · PU',
  printed_ht: 'Total HT imprimé',
}

export default function SourceViewer({ document: doc, highlight, onSelectField, showTech = false }) {
  const canvasRef = useRef(null)
  const [pdfError, setPdfError] = useState('')
  const fields = doc?.fields || {}

  useEffect(() => {
    if (!doc?.url || !canvasRef.current) return
    let cancelled = false
    async function renderPdf() {
      try {
        const pdfjs = await import('pdfjs-dist')
        pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()
        const url = doc.url.startsWith('/') ? `${API_URL}${doc.url}` : doc.url
        const pdf = await pdfjs.getDocument({
          url,
          httpHeaders: { 'X-Role': getRole() },
        }).promise
        const page = await pdf.getPage(1)
        const canvas = canvasRef.current
        const viewport = page.getViewport({ scale: 1.2 })
        canvas.width = viewport.width
        canvas.height = viewport.height
        await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise
      } catch (error) {
        if (!cancelled) setPdfError(`PDF indisponible : ${error.message}`)
      }
    }
    renderPdf()
    return () => { cancelled = true }
  }, [doc?.url, doc?.id])

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-bold">Pièce source · page 1</h3>
        <span className="text-[11px] text-slate-500">{doc?.filename || 'aucune pièce'}</span>
      </div>

      {!doc ? (
        <div className="source-page flex items-center justify-center text-sm text-slate-400">Aucune pièce sélectionnée</div>
      ) : (
        <div className="source-page">
          {doc.url ? (
            <>
              <canvas ref={canvasRef} className="w-full" />
              {pdfError && <p className="p-3 text-xs text-red-600">{pdfError}</p>}
            </>
          ) : (
            <div className="absolute inset-0 p-5">
              <div className="mb-4 text-[10px] uppercase tracking-widest text-slate-400">Aperçu des zones extraites — pièce sans fichier conservé</div>
              {(doc.pageText || []).map((line, index) => (
                <div
                  key={index}
                  className={`source-line ${line.align === 'right' ? 'right-5' : 'left-5'}`}
                  style={{ top: `${line.y}%` }}
                >
                  {line.text}
                </div>
              ))}
            </div>
          )}

          {Object.entries(fields).map(([key, field]) => {
            const box = field.bbox || {}
            return (
              <button
                key={key}
                type="button"
                onClick={() => onSelectField?.(key)}
                title={`${LABELS[key] || key} — ${field.confidence != null ? `${Math.round(field.confidence * 100)} %` : ''}`}
                className={`source-box ${highlight === key ? 'is-active' : ''}`}
                style={{ left: `${box.x ?? 0}%`, top: `${box.y ?? 0}%`, width: `${box.w ?? 20}%`, height: `${box.h ?? 5}%` }}
              >
                <span className="sr-only">{LABELS[key] || key}</span>
              </button>
            )
          })}
        </div>
      )}

      {highlight && fields[highlight] && (
        <div className="mt-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <strong>{LABELS[highlight] || highlight}</strong> · {typeof fields[highlight].value === 'number' && highlight !== 'reference' ? money(fields[highlight].value) : (fields[highlight].value || '— absent —')} · page {fields[highlight].page || 1}
          {showTech && fields[highlight].method && <span> · méthode {fields[highlight].method}</span>}
          {showTech && fields[highlight].confidence != null && <span> · {Math.round(fields[highlight].confidence * 100)} %</span>}
          {fields[highlight].motif && <em> — absent de la pièce</em>}
        </div>
      )}
    </div>
  )
}
