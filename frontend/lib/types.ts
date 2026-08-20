// Types fidèles aux schémas pydantic du backend (profils.py, matching.py, db.py).
// Source de vérité : le backend. En cas d'écart, s'aligner sur pydantic.

export type Verdict =
  | "probablement_eligible"
  | "eligible_sous_conditions"
  | "non_eligible"
  | "erreur";

export type Pertinence = "forte" | "moyenne" | "faible" | null;

export interface Profil {
  id: number;
  user_id: number | null;
  nom: string;
  commune_siege: string;
  region: string;
  langue: string | null;
  secteurs: string[];
  publics_cibles: string[];
  budget_categorie: string | null;
  agrements: string[];
  description_libre: string | null;
  ephemere: boolean;
  type: TypeProfil;
  nom_recherche: string | null;
  profil_hash: string;
  cree_le: string;
  modifie_le: string;
}

// Nature du profil (lot 8.1). Voir profils.TYPES_PROFIL côté backend.
export type TypeProfil = "principal" | "recherche" | "ephemere";

// Une recherche libre sauvegardée, telle que listée dans « Mes recherches ».
export interface Recherche {
  id: number;
  nom_recherche: string;
  commune_siege: string;
  region: string;
  secteurs: string[];
  description_libre: string | null;
  correspondances: number;
  total_analyses: number;
  cree_le: string;
  modifie_le: string;
}

// Ce que le formulaire envoie (POST /profils, PUT /profils/{id}).
export interface ProfilInput {
  nom: string;
  commune_siege: string;
  region?: string;
  langue?: string | null;
  secteurs?: string[];
  publics_cibles?: string[];
  budget_categorie?: string | null;
  agrements?: string[];
  description_libre?: string | null;
}

// Sous-ensemble de la fiche subside embarqué dans un matching (pour l'affichage).
export interface SubsideResume {
  id: number;
  titre: string;
  organisme: string | null;
  source_id: string;
  deadline: string | null;
  permanent: boolean;
  montant: string | null;
  url_source: string;
  lien_officiel: string;   // url_source prête à ouvrir (no_cache=1 si TYPO3)
  zone_categorie: string;
  expire: boolean;
}

export interface Matching {
  id: number;
  profil_id: number;
  subside_id: number;
  verdict: Verdict;
  criteres_satisfaits: string[];
  criteres_a_verifier: string[];
  criteres_non_satisfaits: string[];
  pieces_dossier: string[];
  pertinence: Pertinence;
  justification: string | null;
  cree_le: string;
  subside: SubsideResume;
  depuis_cache?: boolean;
}

export interface JobStatus {
  statut: "running" | "done" | "error";
  profil_id: number;
  total_candidats: number;
  traites: number;
  matchs: number;
  resultats: Matching[];
  erreurs: string[];
  cout_estime_usd: number;
}

export interface Resume {
  total_analyses: number;
  correspondances: number;
  probablement_eligible: number;
  eligible_sous_conditions: number;
  non_eligible: number;
  deadlines_60j: number;
}

export interface DerniereMaj {
  fin: string | null;
  total_subsides: number;
}

// Vue détail : la fiche complète (plus riche que SubsideResume).
export interface SubsideDetail extends SubsideResume {
  zone_geographique: string | null;
  description: string | null;
  public_cible: string | null;
  criteres_eligibilite: string[];
  secteurs: string[];
  lien_candidature: string | null;
  type_beneficiaire: string[];
  langue: string | null;
}

export interface MatchingDetail extends Omit<Matching, "subside"> {
  subside: SubsideDetail;
  recurrence?: Recurrence | null;   // lot 7 : appel annuel récurrent détecté
  profil_type?: TypeProfil;         // lot 8.1 : masque « Préparer » sur une recherche
}

// Tout le dashboard en un appel (perf : pas un appel par carte).
export interface DashboardData {
  profil: { id: number; nom: string; commune_siege: string;
    type?: TypeProfil; nom_recherche?: string | null };
  resume: Resume;
  matchings: Matching[];
  derniere_maj: string | null;
  total_subsides: number;
}

export interface Source {
  id: string;
  nom: string;
  actif: boolean;
  strategie: string;
}

export interface ScrapeRun {
  id: number;
  debut: string;
  fin: string | null;
  resume: {
    duree_secondes: number | null;
    nouveaux: number | null;
    modifies: number | null;
    inchanges: number | null;
    echecs: number | null;
    cout_estime_usd: number | null;
  };
}

export interface SourceSante {
  id: string;
  nom: string;
  actif: boolean;
  strategie: string;
  strategie_utilisee: string | null;
  fiches: number;
  echecs: number;
  dernier_passage: string | null;
  statut_dernier_run: string | null;
  erreurs_dernier_run: string[];
}

// ==================== Étage 3 : candidatures (lot 7) ====================

export type StatutCandidature =
  | "a_etudier" | "dossier_en_cours" | "soumis" | "obtenu" | "refuse" | "abandonne";

export interface SubsideCarte {
  id: number;
  titre: string;
  organisme: string | null;
  deadline: string | null;
  permanent: boolean;
  url_source: string;
  lien_officiel?: string;
  source_id: string;
  expire?: boolean;
}

export interface Candidature {
  id: number;
  profil_id: number;
  subside_id: number;
  matching_id: number | null;
  statut: StatutCandidature;
  montant_demande: number | null;
  montant_obtenu: number | null;
  date_soumission: string | null;
  date_decision: string | null;
  notes: string | null;
  cree_le: string;
  modifie_le: string;
  subside: SubsideCarte | null;
}

export interface CandidatureStats {
  total_candidatures: number;
  total_demande: number;
  total_obtenu: number;
  decisions: number;
  taux_succes: number | null;
}

export interface ChecklistItem {
  id: number;
  candidature_id: number;
  intitule: string;
  type: "document" | "formulaire" | "condition_forme";
  source_citation: string | null;
  origine: "llm" | "utilisateur";
  coche: number;
}

export interface ChecklistEtat {
  items: ChecklistItem[];
  generee: boolean;
  texte_absent: boolean;
  fiche_a_change: boolean;
  depuis_cache?: boolean;
  erreur?: string;
  cout?: number;
}

export interface Recurrence {
  frere_id: number;
  frere_titre: string;
  annee: string | null;
  annee_courante: string | null;
}

export interface CopiloteMessage {
  action: "structurer" | "relire" | "reformuler";
  entree: string;
  sortie: string;
  cree_le: string;
}

export interface Conformite {
  points_conformes: string[];
  points_manquants: string[];
  points_a_clarifier: string[];
  avertissements: string[];
  depuis_cache?: boolean;
  erreur?: string;
  cout?: number;
}

// Candidature enrichie renvoyée par GET /candidature/{id}
export interface CandidatureDetail extends Candidature {
  subside: (SubsideCarte & Record<string, unknown>) | null;
  checklist: ChecklistEtat;
  copilote: CopiloteMessage[];
  recurrence: Recurrence | null;
}
