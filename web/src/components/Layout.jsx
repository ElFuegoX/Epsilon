import { useState } from 'react'

const ROLE_HINTS = {
  dirigeant: 'Responsable comptable : valide, numérote, émet les avoirs, crée les clients',
  assistante: 'Opérateur facturation : importe, prépare et envoie les brouillons',
  lecture: 'Auditeur : consulte le registre, vérifie et exporte le journal',
}

const NOTICE_STYLES = {
  success: 'border-emerald-300 bg-emerald-50 text-emerald-900',
  info: 'border-sky-300 bg-sky-50 text-sky-900',
  error: 'border-red-300 bg-red-50 text-red-800',
}

const BADGE_STYLES = {
  red: 'bg-red-600 text-white',
  amber: 'bg-amber-500 text-amber-950',
  emerald: 'bg-emerald-600 text-white',
}

export default function Layout({
  tabs,
  active,
  onSelect,
  role,
  onRole,
  onReset,
  badges = {},
  mode,
  notice,
  onDismissNotice,
  children,
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const workflowTabs = tabs.filter((t) => t.group !== 'global')
  const globalTabs = tabs.filter((t) => t.group === 'global')

  const renderTab = (tab, index, showNumber) => {
    const badge = badges[tab.id]
    const isActive = active === tab.id
    return (
      <button
        key={tab.id}
        onClick={() => { onSelect(tab.id); setMenuOpen(false) }}
        className={`flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-2 text-xs font-medium transition ${
          isActive
            ? 'bg-slate-900 text-white shadow-sm'
            : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
        }`}
      >
        {showNumber && <span className="text-[10px] opacity-60">{index + 1}</span>}
        <span>{tab.label}</span>
        {badge && (
          <span
            className={`ml-0.5 inline-flex min-w-[18px] items-center justify-center rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
              isActive ? 'bg-white/20 text-white' : (BADGE_STYLES[badge.tone] || 'bg-slate-200 text-slate-800')
            }`}
          >
            {badge.count}
          </span>
        )}
      </button>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="bg-amber-300 px-4 py-1 text-center text-xs font-bold uppercase tracking-widest text-amber-950">
        Simulation — prototype non agréé, aucune donnée réelle
      </div>

      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <button
              className="rounded border border-slate-300 px-2 py-1 text-sm md:hidden"
              onClick={() => setMenuOpen((v) => !v)}
              aria-label="Ouvrir le menu"
            >
              ☰
            </button>
            <div>
              <h1 className="text-lg font-black tracking-tight">WÉMA</h1>
              <p className="text-[11px] text-slate-500">facturation vérifiable · source, calcul, décision</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-600">{mode}</span>
            <div className="flex items-center gap-2">
              <label className="sr-only" htmlFor="role">Rôle</label>
              <select
                id="role"
                value={role}
                onChange={(e) => onRole(e.target.value)}
                className="rounded border border-slate-300 bg-white px-2.5 py-1 font-medium"
              >
                <option value="dirigeant">Responsable comptable / Dirigeant</option>
                <option value="assistante">Opérateur facturation / Commercial</option>
                <option value="lecture">Auditeur (Lecture seule)</option>
              </select>
              <span className="hidden text-[11px] text-slate-500 lg:inline">{ROLE_HINTS[role]}</span>
            </div>
            {role === 'dirigeant' && onReset && (
              <button
                type="button"
                onClick={onReset}
                title="Réinitialiser la base de démonstration"
                className="rounded border border-slate-300 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100"
              >
                Remettre à zéro
              </button>
            )}
          </div>
        </div>

        <nav className={`${menuOpen ? 'block' : 'hidden'} border-t border-slate-100 md:block`}>
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-2">
            <div className="flex items-center gap-1 overflow-x-auto">
              <span className="mr-1 hidden text-[10px] font-semibold uppercase tracking-wider text-slate-400 xl:inline">
                Dossier :
              </span>
              {workflowTabs.map((tab, idx) => renderTab(tab, idx, true))}
            </div>

            {globalTabs.length > 0 && (
              <div className="flex items-center gap-1 border-t border-slate-100 pt-2 md:border-l md:border-t-0 md:pl-3 md:pt-0">
                <span className="mr-1 hidden text-[10px] font-semibold uppercase tracking-wider text-slate-400 xl:inline">
                  Archives :
                </span>
                {globalTabs.map((tab, idx) => renderTab(tab, idx, false))}
              </div>
            )}
          </div>
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        {notice && (
          <div
            className={`mb-4 flex items-start justify-between gap-3 rounded-lg border px-4 py-3 text-sm ${
              NOTICE_STYLES[notice.type] || NOTICE_STYLES.info
            }`}
            role="alert"
          >
            <span>{notice.text || String(notice)}</span>
            {onDismissNotice && (
              <button
                type="button"
                onClick={onDismissNotice}
                aria-label="Fermer le message"
                className="rounded px-1.5 text-xs font-bold opacity-60 hover:opacity-100"
              >
                ×
              </button>
            )}
          </div>
        )}
        {children}
      </main>
    </div>
  )
}
