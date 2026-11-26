const ROLE_HINTS = {
  dirigeant: 'Valide, numérote, émet les avoirs et crée les clients',
  assistante: 'Importe, prépare les brouillons et relance les clients',
  lecture: 'Consulte le registre, vérifie et exporte le journal',
}

const NOTICE_STYLES = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  info: 'border-sky-200 bg-sky-50 text-sky-900',
  error: 'border-red-200 bg-red-50 text-red-800',
}

const BADGE_STYLES = {
  red: 'bg-red-600 text-white',
  amber: 'bg-amber-400 text-amber-950',
  emerald: 'bg-emerald-600 text-white',
}

// 4 sections principales exactement comme dans la maquette Proposition 3
const PRIMARY_SECTIONS = [
  { id: 'inbox', label: 'Entrée', tabs: ['inbox'], badgeKey: 'inbox' },
  {
    id: 'controls',
    label: 'Vérifier',
    tabs: ['controls', 'analysis', 'lines', 'reconciliation', 'preview'],
    badgeKey: 'controls',
  },
  { id: 'validation', label: 'Valider', tabs: ['validation'] },
  {
    id: 'register',
    label: 'Registre',
    tabs: ['register', 'referentials', 'audit'],
    badgeKey: 'register',
  },
]

const SUB_TABS = {
  controls: [
    { id: 'controls', label: 'Anomalies à traiter' },
    { id: 'analysis', label: 'Pièce & sources' },
    { id: 'lines', label: 'Lignes' },
    { id: 'reconciliation', label: 'Livraison' },
    { id: 'preview', label: 'Aperçu facture' },
  ],
  register: [
    { id: 'register', label: 'Factures & avoirs' },
    { id: 'audit', label: 'Journal d’audit' },
    { id: 'referentials', label: 'Clients & tarifs' },
  ],
}

export default function Layout({
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
  const currentSection =
    PRIMARY_SECTIONS.find((s) => s.tabs.includes(active)) || PRIMARY_SECTIONS[0]
  const subTabs = SUB_TABS[currentSection.id] || []

  return (
    <div className="min-h-screen bg-[#f4f7f6] pb-24 text-slate-900 md:pb-10">
      {/* Bandeau Simulation */}
      <div className="bg-amber-400 px-4 py-1.5 text-center text-[11px] font-extrabold uppercase tracking-wider text-amber-950">
        Simulation — prototype non agréé, aucune donnée réelle
      </div>

      {/* En-tête Fintech Terrain épuré */}
      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => onSelect('inbox')}
              className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-600 to-teal-700 text-lg font-black text-white shadow-sm transition hover:scale-105"
              aria-label="Accueil WÉMA"
            >
              W
            </button>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-black tracking-tight text-slate-900">WÉMA</h1>
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
                  {mode}
                </span>
              </div>
              <p className="text-[11px] text-slate-500">{ROLE_HINTS[role]}</p>
            </div>
          </div>

          {/* 4 sections principales sur desktop (comme la maquette) */}
          <nav className="hidden items-center gap-1 rounded-2xl border border-slate-200/80 bg-slate-50 p-1 md:flex">
            {PRIMARY_SECTIONS.map((sec) => {
              const isActive = currentSection.id === sec.id
              const badge = sec.badgeKey ? badges[sec.badgeKey] : null
              return (
                <button
                  key={sec.id}
                  type="button"
                  onClick={() => onSelect(sec.id)}
                  className={`flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-bold transition ${
                    isActive
                      ? 'bg-emerald-600 text-white shadow-sm'
                      : 'text-slate-600 hover:bg-white hover:text-slate-900'
                  }`}
                >
                  <span>{sec.label}</span>
                  {badge && (
                    <span
                      className={`ml-0.5 inline-flex min-w-[18px] items-center justify-center rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                        isActive ? 'bg-white/25 text-white' : (BADGE_STYLES[badge.tone] || 'bg-slate-200 text-slate-800')
                      }`}
                    >
                      {badge.count}
                    </span>
                  )}
                </button>
              )
            })}
          </nav>

          {/* Poste & Reset */}
          <div className="flex items-center gap-2 text-xs">
            <label className="sr-only" htmlFor="role">Poste</label>
            <select
              id="role"
              value={role}
              onChange={(e) => onRole(e.target.value)}
              className="rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-2 text-xs font-semibold text-slate-800 focus:border-emerald-500 focus:outline-none"
            >
              <option value="dirigeant">Dirigeant / Comptable</option>
              <option value="assistante">Opérateur / Commercial</option>
              <option value="lecture">Auditeur (Lecture)</option>
            </select>

            {role === 'dirigeant' && onReset && (
              <button
                type="button"
                onClick={onReset}
                title="Réinitialiser la démonstration"
                className="rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100"
              >
                ↺
              </button>
            )}
          </div>
        </div>

        {/* Sous-onglets compacts uniquement quand on est dans Vérifier ou Registre */}
        {subTabs.length > 0 && (
          <div className="border-t border-slate-100 bg-white">
            <div className="mx-auto flex max-w-5xl items-center gap-1.5 overflow-x-auto px-4 py-2">
              {subTabs.map((sub) => {
                const isSubActive = active === sub.id
                return (
                  <button
                    key={sub.id}
                    type="button"
                    onClick={() => onSelect(sub.id)}
                    className={`whitespace-nowrap rounded-xl px-3 py-1.5 text-xs font-semibold transition ${
                      isSubActive
                        ? 'bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200'
                        : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
                    }`}
                  >
                    {sub.label}
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </header>

      {/* Contenu principal centré (plus aéré et proche de la maquette) */}
      <main className="mx-auto max-w-5xl px-4 py-6">
        {notice && (
          <div
            className={`mb-4 flex items-start justify-between gap-3 rounded-2xl border px-4 py-3 text-sm font-medium shadow-sm ${
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
                className="rounded-lg px-2 py-0.5 text-xs font-bold opacity-60 hover:opacity-100"
              >
                ×
              </button>
            )}
          </div>
        )}
        {children}
      </main>

      {/* Barre de navigation basse mobile (exactement les 4 boutons de la maquette) */}
      <nav className="fixed bottom-0 left-0 right-0 z-30 grid grid-cols-4 gap-1 border-t border-slate-200 bg-white/95 px-2 py-2 backdrop-blur md:hidden">
        {PRIMARY_SECTIONS.map((sec) => {
          const isActive = currentSection.id === sec.id
          const badge = sec.badgeKey ? badges[sec.badgeKey] : null
          return (
            <button
              key={sec.id}
              type="button"
              onClick={() => onSelect(sec.id)}
              className={`relative flex flex-col items-center gap-0.5 rounded-xl py-1.5 text-[11px] font-bold transition ${
                isActive ? 'bg-emerald-50 text-emerald-700' : 'text-slate-500'
              }`}
            >
              <span className="py-1">{sec.label}</span>
              {badge && (
                <span
                  className={`absolute right-3 top-0.5 inline-flex min-w-[16px] items-center justify-center rounded-full px-1 text-[9px] font-bold ${
                    BADGE_STYLES[badge.tone] || 'bg-slate-600 text-white'
                  }`}
                >
                  {badge.count}
                </span>
              )}
            </button>
          )
        })}
      </nav>
    </div>
  )
}
