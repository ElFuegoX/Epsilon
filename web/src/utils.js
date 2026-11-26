export const fmt = (n) => (typeof n === 'number' ? new Intl.NumberFormat('fr-FR').format(n) : '—')

export const money = (n) => (typeof n === 'number' ? `${fmt(n)} FCFA` : '—')

export const copyToClipboard = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export const statusColor = (status) => {
  if (status === 'EXTRAIT' || status === 'VALIDE' || status === 'EMISE' || status === 'RESOLUE') return 'bg-emerald-100 text-emerald-800'
  if (status === 'EN_ATTENTE_IA' || status === 'EN_ATTENTE') return 'bg-amber-100 text-amber-800'
  return 'bg-slate-100 text-slate-700'
}
