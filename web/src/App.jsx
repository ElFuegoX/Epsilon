import { useCallback, useEffect, useState } from 'react'
import Layout from './components/Layout'
import Inbox from './components/Inbox'
import Analysis from './components/Analysis'
import Lines from './components/Lines'
import Controls from './components/Controls'
import Reconciliation from './components/Reconciliation'
import Preview from './components/Preview'
import Validation from './components/Validation'
import Register from './components/Register'
import Referentials from './components/Referentials'
import Audit from './components/Audit'
import { api, setRole, USE_MOCK, DEFAULT_ROLE } from './api.js'
import { normalizeDocument, normalizeDraft, normalizeInvoice } from './normalize.js'
import { fmt } from './utils.js'

const TABS = [
  { id: 'inbox', label: "Boîte d'entrée", group: 'workflow' },
  { id: 'analysis', label: 'Analyse', group: 'workflow' },
  { id: 'lines', label: 'Lignes', group: 'workflow' },
  { id: 'controls', label: 'Contrôles', group: 'workflow' },
  { id: 'reconciliation', label: 'Rapprochement', group: 'workflow' },
  { id: 'preview', label: 'Aperçu', group: 'workflow' },
  { id: 'validation', label: 'Validation', group: 'workflow' },
  { id: 'register', label: 'Registre', group: 'global' },
  { id: 'referentials', label: 'Référentiels', group: 'global' },
  { id: 'audit', label: 'Journal', group: 'global' },
]

const unwrap = (value) => (Array.isArray(value?.items) ? value.items : [])

export default function App() {
  const [tab, setTab] = useState('inbox')
  const [role, setRoleState] = useState(DEFAULT_ROLE)
  const [data, setData] = useState({ documents: [], drafts: [], anomalies: [], invoices: [], audit: [], clients: [], items: [] })
  const [selectedDocumentId, setSelectedDocumentId] = useState(null)
  const [selectedDraftId, setSelectedDraftId] = useState(null)
  const [highlight, setHighlight] = useState(null)
  const [notice, setNoticeState] = useState(null)

  const setNotice = useCallback((value, explicitType = null) => {
    if (!value) {
      setNoticeState(null)
      return
    }
    if (typeof value === 'object' && value.text) {
      setNoticeState(value)
      return
    }
    const text = String(value)
    let type = explicitType
    if (!type) {
      if (/validée|résolue|prêt à copier|réinitialis|émise|créé/i.test(text)) type = 'success'
      else if (/403|409|422|erreur|interdit|refus|impossible|introuvable|manquant/i.test(text)) type = 'error'
      else type = 'info'
    }
    setNoticeState({ type, text })
  }, [])

  const refresh = useCallback(async (preferredDraftId = null) => {
    try {
      const [documentsRes, draftsRes, invoicesRes, auditRes, clientsRes, itemsRes] = await Promise.all([
        api.listDocuments(),
        api.listDrafts(),
        api.listInvoices(),
        api.audit(),
        api.clients(),
        api.items(),
      ])
      const clients = unwrap(clientsRes)
      const documents = unwrap(documentsRes).map(normalizeDocument)
      const drafts = unwrap(draftsRes).map((d) => normalizeDraft(d, documents, clients))
      const activeDraftId =
        preferredDraftId ||
        (drafts.some((d) => d.id === selectedDraftId) ? selectedDraftId : drafts[0]?.id) ||
        null

      let anomalies = []
      if (activeDraftId) {
        try {
          anomalies = unwrap(await api.listAnomalies(activeDraftId))
        } catch {
          anomalies = []
        }
      }

      setData({
        documents,
        drafts,
        anomalies,
        invoices: unwrap(invoicesRes).map((i) => normalizeInvoice(i, clients)),
        audit: unwrap(auditRes),
        clients,
        items: unwrap(itemsRes),
      })
      if (activeDraftId && activeDraftId !== selectedDraftId) {
        setSelectedDraftId(activeDraftId)
      }
      if (!selectedDocumentId && documents[0]?.id) {
        setSelectedDocumentId(documents[0].id)
      }
    } catch (error) {
      setNotice(error.message)
    }
  }, [selectedDraftId, selectedDocumentId])

  useEffect(() => { refresh() }, [refresh])

  const run = useCallback(async (action, { nextDraftId } = {}) => {
    setNotice('')
    try {
      const result = await action()
      await refresh(nextDraftId || result?.draft_id || null)
      return result
    } catch (error) {
      setNotice(error.message || String(error))
      return null
    }
  }, [refresh])

  const changeRole = (next) => {
    setRoleState(next)
    setRole(next)
  }

  const openDocument = (id, explicitDraftId = null) => {
    setSelectedDocumentId(id)
    const linkedDraft = explicitDraftId
      ? { id: explicitDraftId }
      : data.drafts.find((d) => d.document_id === id)
    if (linkedDraft?.id) {
      setSelectedDraftId(linkedDraft.id)
      refresh(linkedDraft.id)
    }
    setHighlight(null)
    setTab('analysis')
  }

  const document = data.documents.find((d) => d.id === selectedDocumentId) || data.documents[0]
  const draft = data.drafts.find((d) => d.id === selectedDraftId) || data.drafts[0]
  const invoice = data.invoices[0]

  const resetDemo = () => run(async () => {
    await api.reset()
    setSelectedDocumentId(null)
    setSelectedDraftId(null)
    setHighlight(null)
    setTab('inbox')
    setNotice({ type: 'success', text: 'Démonstration réinitialisée au propre.' })
  })

  const shared = { data, role, run, notice, setNotice, go: setTab, fmt, highlight, setHighlight, document, draft, invoice }

  const screens = {
    inbox: <Inbox {...shared} onOpen={openDocument} />,
    analysis: <Analysis {...shared} />,
    lines: <Lines {...shared} />,
    controls: <Controls {...shared} />,
    reconciliation: <Reconciliation {...shared} />,
    preview: <Preview {...shared} />,
    validation: <Validation {...shared} />,
    register: <Register {...shared} />,
    referentials: <Referentials {...shared} />,
    audit: <Audit {...shared} />,
  }

  const openAnomaliesCount = data.anomalies.filter((a) => a.status !== 'RESOLUE').length
  const waitingDocsCount = data.documents.filter((d) => d.status === 'EN_ATTENTE_IA').length
  const badges = {
    inbox: waitingDocsCount > 0 ? { count: waitingDocsCount, tone: 'amber' } : null,
    controls: openAnomaliesCount > 0 ? { count: openAnomaliesCount, tone: 'red' } : null,
    register: data.invoices.length > 0 ? { count: data.invoices.length, tone: 'emerald' } : null,
  }

  return (
    <Layout
      tabs={TABS}
      active={tab}
      onSelect={setTab}
      role={role}
      onRole={changeRole}
      onReset={resetDemo}
      badges={badges}
      mode={USE_MOCK ? 'Mode démo' : `API ${import.meta.env.VITE_API_URL || 'locale'}`}
      notice={notice}
      onDismissNotice={() => setNotice(null)}
    >
      {screens[tab]}
    </Layout>
  )
}
