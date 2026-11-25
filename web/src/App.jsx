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
import { fmt } from './utils.js'

const TABS = [
  { id: 'inbox', label: "Boîte d'entrée" },
  { id: 'analysis', label: 'Analyse' },
  { id: 'lines', label: 'Lignes' },
  { id: 'controls', label: 'Contrôles' },
  { id: 'reconciliation', label: 'Rapprochement' },
  { id: 'preview', label: 'Aperçu' },
  { id: 'validation', label: 'Validation' },
  { id: 'register', label: 'Registre' },
  { id: 'referentials', label: 'Référentiels' },
  { id: 'audit', label: 'Journal' },
]

const unwrap = (value) => (Array.isArray(value?.items) ? value.items : [])

export default function App() {
  const [tab, setTab] = useState('inbox')
  const [role, setRoleState] = useState(DEFAULT_ROLE)
  const [data, setData] = useState({ documents: [], drafts: [], anomalies: [], invoices: [], audit: [], clients: [], items: [] })
  const [selectedDocumentId, setSelectedDocumentId] = useState('doc-041')
  const [selectedDraftId, setSelectedDraftId] = useState('draft-041')
  const [highlight, setHighlight] = useState(null)
  const [notice, setNotice] = useState('')

  const refresh = useCallback(async () => {
    try {
      const [documents, drafts, anomalies, invoices, audit, clients, items] = await Promise.all([
        api.listDocuments(), api.listDrafts(), api.listAnomalies('draft-041'),
        api.listInvoices(), api.audit(), api.clients(), api.items(),
      ])
      setData({
        documents: unwrap(documents), drafts: unwrap(drafts), anomalies: unwrap(anomalies),
        invoices: unwrap(invoices), audit: unwrap(audit), clients: unwrap(clients), items: unwrap(items),
      })
    } catch (error) {
      setNotice(error.message)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const run = useCallback(async (action) => {
    setNotice('')
    try {
      await action()
      await refresh()
    } catch (error) {
      setNotice(error.message || String(error))
    }
  }, [refresh])

  const changeRole = (next) => {
    setRoleState(next)
    setRole(next)
  }

  const openDocument = (id) => {
    setSelectedDocumentId(id)
    const draft = data.drafts.find((d) => d.document_id === id)
    if (draft) setSelectedDraftId(draft.id)
    setHighlight(null)
    setTab('analysis')
  }

  const document = data.documents.find((d) => d.id === selectedDocumentId) || data.documents[0]
  const draft = data.drafts.find((d) => d.id === selectedDraftId) || data.drafts[0]
  const invoice = data.invoices[0]

  const shared = { data, run, notice, setNotice, go: setTab, fmt, highlight, setHighlight, document, draft, invoice }

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

  return (
    <Layout
      tabs={TABS}
      active={tab}
      onSelect={setTab}
      role={role}
      onRole={changeRole}
      mode={USE_MOCK ? 'Mock déterministe' : `API ${import.meta.env.VITE_API_URL || 'http://localhost:8000'}`}
      notice={notice}
    >
      {screens[tab]}
    </Layout>
  )
}
