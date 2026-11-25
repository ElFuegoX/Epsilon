-- WÉMA : schéma SQLite (WAL). Une vingtaine de tables, dont une douzaine
-- réellement indispensables au MVP. Les montants sont des entiers FCFA.

CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,
    nom          TEXT NOT NULL,
    mime         TEXT NOT NULL,
    taille       INTEGER NOT NULL,
    hash         TEXT NOT NULL UNIQUE,
    pages        INTEGER NOT NULL DEFAULT 0,
    canal        TEXT,
    statut       TEXT NOT NULL,
    cree_le      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_pages (
    id           TEXT PRIMARY KEY,
    document     TEXT NOT NULL REFERENCES documents(id),
    numero       INTEGER NOT NULL,
    chemin       TEXT NOT NULL,
    largeur      INTEGER,
    hauteur      INTEGER,
    texte_ocr    TEXT,
    UNIQUE(document, numero)
);

CREATE TABLE IF NOT EXISTS extractions (
    id           TEXT PRIMARY KEY,
    document     TEXT NOT NULL REFERENCES documents(id),
    modele       TEXT NOT NULL,
    version      TEXT NOT NULL,
    date         TEXT NOT NULL,
    brut_json    TEXT NOT NULL,
    duree_ms     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS extracted_fields (
    id                TEXT PRIMARY KEY,
    extraction        TEXT NOT NULL REFERENCES extractions(id),
    chemin            TEXT NOT NULL,
    valeur            TEXT,
    valeur_normalisee TEXT,
    confiance         REAL NOT NULL DEFAULT 0,
    page              INTEGER,
    bbox              TEXT,
    methode           TEXT,
    missing           TEXT
);

CREATE TABLE IF NOT EXISTS clients (
    id              TEXT PRIMARY KEY,
    raison_sociale  TEXT NOT NULL,
    ifu             TEXT UNIQUE,
    adresse         TEXT,
    ville           TEXT,
    telephone       TEXT,
    conditions      TEXT
);

CREATE TABLE IF NOT EXISTS items (
    id              TEXT PRIMARY KEY,
    reference       TEXT NOT NULL UNIQUE,
    designation     TEXT NOT NULL,
    unite           TEXT NOT NULL,
    prix_catalogue  INTEGER NOT NULL,
    famille         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_lists (
    id           TEXT PRIMARY KEY,
    article      TEXT NOT NULL REFERENCES items(id),
    prix         INTEGER NOT NULL,
    devise       TEXT NOT NULL,
    date_debut   TEXT NOT NULL,
    date_fin     TEXT
);

CREATE TABLE IF NOT EXISTS tax_codes (
    code         TEXT PRIMARY KEY,
    libelle      TEXT NOT NULL,
    taux_bp      INTEGER NOT NULL,
    exoneration  INTEGER NOT NULL DEFAULT 0,
    compte       TEXT
);

CREATE TABLE IF NOT EXISTS payment_terms (
    code         TEXT PRIMARY KEY,
    libelle      TEXT NOT NULL,
    delai_jours  INTEGER NOT NULL,
    echeancier   TEXT
);

CREATE TABLE IF NOT EXISTS invoice_drafts (
    id            TEXT PRIMARY KEY,
    document      TEXT REFERENCES documents(id),
    client        TEXT REFERENCES clients(id),
    date_piece    TEXT,
    date_echeance TEXT,
    conditions    TEXT,
    version       INTEGER NOT NULL DEFAULT 1,
    statut        TEXT NOT NULL,
    cree_le       TEXT NOT NULL,
    modifie_le    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS draft_lines (
    id          TEXT PRIMARY KEY,
    draft       TEXT NOT NULL REFERENCES invoice_drafts(id),
    numero      INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantite    TEXT NOT NULL,
    unite       TEXT NOT NULL,
    pu_ht       INTEGER NOT NULL,
    remise      INTEGER NOT NULL DEFAULT 0,
    remise_pct  INTEGER NOT NULL DEFAULT 0,
    tax_code    TEXT NOT NULL,
    total_ht    INTEGER NOT NULL,
    item        TEXT,
    famille     TEXT,
    UNIQUE(draft, numero)
);

CREATE TABLE IF NOT EXISTS document_totals (
    document      TEXT PRIMARY KEY REFERENCES documents(id),
    printed_ht    INTEGER,
    printed_vat   INTEGER,
    printed_ttc   INTEGER
);

CREATE TABLE IF NOT EXISTS deliveries (
    id               TEXT PRIMARY KEY,
    draft            TEXT NOT NULL REFERENCES invoice_drafts(id),
    numero           INTEGER NOT NULL,
    quantite_livree  TEXT NOT NULL,
    decision         TEXT NOT NULL DEFAULT 'A_DECIDER',
    motif            TEXT,
    UNIQUE(draft, numero)
);

CREATE TABLE IF NOT EXISTS anomalies (
    id          TEXT PRIMARY KEY,
    draft       TEXT NOT NULL REFERENCES invoice_drafts(id),
    code        TEXT NOT NULL,
    severite    TEXT NOT NULL,
    champ       TEXT,
    message     TEXT NOT NULL,
    statut      TEXT NOT NULL DEFAULT 'OUVERTE',
    resolution  TEXT,
    avant       TEXT,
    apres       TEXT
);

CREATE TABLE IF NOT EXISTS invoices (
    id             TEXT PRIMARY KEY,
    numero         TEXT NOT NULL,
    serie          TEXT NOT NULL,
    annee          INTEGER NOT NULL,
    snapshot       TEXT NOT NULL,
    hash_snapshot  TEXT NOT NULL,
    hash_pdf       TEXT NOT NULL,
    date           TEXT NOT NULL,
    statut         TEXT NOT NULL,
    mecef_ref      TEXT,
    canal          TEXT,
    client         TEXT,
    empreinte      TEXT,
    total_ht       INTEGER NOT NULL,
    total_tva      INTEGER NOT NULL,
    total_ttc      INTEGER NOT NULL,
    UNIQUE(serie, annee, numero)
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id          TEXT PRIMARY KEY,
    facture     TEXT NOT NULL REFERENCES invoices(id),
    numero      INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantite    TEXT NOT NULL,
    unite       TEXT NOT NULL,
    pu_ht       INTEGER NOT NULL,
    remise      INTEGER NOT NULL DEFAULT 0,
    tax_code    TEXT NOT NULL,
    total_ht    INTEGER NOT NULL,
    tva         INTEGER NOT NULL,
    UNIQUE(facture, numero)
);

CREATE TABLE IF NOT EXISTS credit_notes (
    id          TEXT PRIMARY KEY,
    numero      TEXT NOT NULL,
    serie       TEXT NOT NULL,
    annee       INTEGER NOT NULL,
    facture     TEXT NOT NULL REFERENCES invoices(id),
    motif       TEXT NOT NULL,
    total_ht    INTEGER NOT NULL,
    total_tva   INTEGER NOT NULL,
    total_ttc   INTEGER NOT NULL,
    statut      TEXT NOT NULL,
    cree_le     TEXT NOT NULL,
    UNIQUE(serie, annee, numero)
);

CREATE TABLE IF NOT EXISTS payments (
    id          TEXT PRIMARY KEY,
    facture     TEXT NOT NULL REFERENCES invoices(id),
    montant     INTEGER NOT NULL,
    date        TEXT NOT NULL,
    canal       TEXT,
    reference   TEXT
);

CREATE TABLE IF NOT EXISTS number_sequences (
    serie       TEXT NOT NULL,
    annee       INTEGER NOT NULL,
    prefixe     TEXT NOT NULL,
    prochaine   INTEGER NOT NULL DEFAULT 1,
    version     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(serie, annee, prefixe)
);

CREATE TABLE IF NOT EXISTS audit_events (
    sequence    INTEGER PRIMARY KEY AUTOINCREMENT,
    acteur      TEXT NOT NULL,
    action      TEXT NOT NULL,
    avant       TEXT,
    apres       TEXT,
    horodatage  TEXT NOT NULL,
    hash        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    cle         TEXT PRIMARY KEY,
    action      TEXT NOT NULL,
    resultat    TEXT NOT NULL,
    date        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_items (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    entite      TEXT NOT NULL,
    motif       TEXT NOT NULL,
    priorite    TEXT NOT NULL,
    assigne     TEXT,
    resolution  TEXT
);

-- Immutabilité de la facture validée : seuls le statut, le canal, la
-- référence MECeF simulée et la date d'émission peuvent encore changer.
CREATE TRIGGER IF NOT EXISTS trg_invoice_immutable_update
BEFORE UPDATE ON invoices
WHEN OLD.statut IN ('VALIDÉ', 'ÉMIS', 'ANNULÉ_PAR_AVOIR')
 AND (NEW.numero <> OLD.numero
      OR NEW.snapshot <> OLD.snapshot
      OR NEW.hash_snapshot <> OLD.hash_snapshot
      OR NEW.hash_pdf <> OLD.hash_pdf
      OR NEW.total_ht <> OLD.total_ht
      OR NEW.total_tva <> OLD.total_tva
      OR NEW.total_ttc <> OLD.total_ttc
      OR NEW.client <> OLD.client
      OR NEW.date <> OLD.date)
BEGIN
    SELECT RAISE(ABORT, 'INVOICE_IMMUTABLE');
END;

CREATE TRIGGER IF NOT EXISTS trg_invoice_immutable_delete
BEFORE DELETE ON invoices
WHEN OLD.statut IN ('VALIDÉ', 'ÉMIS', 'ANNULÉ_PAR_AVOIR')
BEGIN
    SELECT RAISE(ABORT, 'INVOICE_IMMUTABLE');
END;

CREATE INDEX IF NOT EXISTS idx_docs_statut ON documents(statut);
CREATE INDEX IF NOT EXISTS idx_drafts_statut ON invoice_drafts(statut);
CREATE INDEX IF NOT EXISTS idx_anomalies_draft ON anomalies(draft);
CREATE INDEX IF NOT EXISTS idx_invoices_numero ON invoices(numero);
