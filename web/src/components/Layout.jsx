import { useState } from 'react'

export default function Layout({ tabs, active, onSelect, role, onRole, mode, notice, children }) {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="bg-amber-300 px-4 py-1 text-center text-xs font-bold uppercase tracking-widest text-amber-950">
        Simulation — prototype non agréé, aucune donnée réelle
      </div>

      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3">
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

          <div className="flex items-center gap-2 text-xs">
            <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-600">{mode}</span>
            <label className="sr-only" htmlFor="role">Rôle</label>
            <select
              id="role"
              value={role}
              onChange={(e) => onRole(e.target.value)}
              className="rounded border border-slate-300 bg-white px-2 py-1"
            >
              <option value="dirigeant">dirigeant</option>
              <option value="assistante">assistante</option>
              <option value="lecture">lecture</option>
            </select>
          </div>
        </div>

        <nav className={`${menuOpen ? 'block' : 'hidden'} md:block`}>
          <div className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pb-2">
            {tabs.map((tab, index) => (
              <button
                key={tab.id}
                onClick={() => { onSelect(tab.id); setMenuOpen(false) }}
                className={`whitespace-nowrap rounded px-3 py-2 text-xs font-medium transition ${active === tab.id ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
              >
                <span className="mr-1 text-[10px] opacity-60">{index + 1}</span>
                {tab.label}
              </button>
            ))}
          </div>
        </nav>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        {notice && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
            {notice}
          </div>
        )}
        {children}
      </main>
    </div>
  )
}
