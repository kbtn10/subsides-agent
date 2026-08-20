// Client API : le frontend ne parle QU'À FastAPI (aucun accès direct à la base,
// aucun appel Anthropic ici). Le token Clerk est passé en Bearer.

import { API_URL } from "./constants";
import type {
  Candidature, CandidatureDetail, CandidatureStats, ChecklistEtat, ChecklistItem,
  Conformite, DashboardData, DerniereMaj, JobStatus, Matching, MatchingDetail,
  Obligation, ObligationEcheance, ObligationsEtat,
  Profil, ProfilInput, Recherche, RegistreEntry, Resume, ScrapeRun, Source, SourceSante,
  StatutCandidature,
} from "./types";

// getToken vient du hook Clerk useAuth() — on l'injecte pour rester testable
// et éviter tout couplage dur.
type GetToken = () => Promise<string | null>;

async function req<T>(
  path: string,
  { method = "GET", body, getToken }: { method?: string; body?: unknown; getToken?: GetToken } = {},
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (getToken) {
    const t = await getToken();
    if (t) headers["Authorization"] = `Bearer ${t}`;
  }
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `Erreur ${res.status}`;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* garde le message par défaut */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export const api = {
  creerProfil: (body: ProfilInput, getToken?: GetToken) =>
    req<Profil>("/profils", { method: "POST", body, getToken }),

  majProfil: (id: number, body: ProfilInput, getToken?: GetToken) =>
    req<Profil>(`/profils/${id}`, { method: "PUT", body, getToken }),

  mesProfils: (getToken?: GetToken) => req<Profil[]>("/profils", { getToken }),

  getProfil: (id: number, getToken?: GetToken) =>
    req<Profil>(`/profils/${id}`, { getToken }),

  supprimerProfil: (id: number, getToken?: GetToken) =>
    req<{ supprime: boolean }>(`/profils/${id}`, { method: "DELETE", getToken }),

  lancerMatching: (profilId: number, getToken?: GetToken) =>
    req<{ job_id: string }>(`/matching/${profilId}`, { method: "POST", getToken }),

  rechercheLibre: (body: ProfilInput, getToken?: GetToken) =>
    req<{ profil_id: number; job_id: string; ephemere: boolean }>(
      "/matching/recherche", { method: "POST", body, getToken }),

  // --- Recherches sauvegardées (lot 8.1) ---
  mesRecherches: (getToken?: GetToken) =>
    req<{ recherches: Recherche[]; max: number }>("/recherches", { getToken }),

  sauvegarderRecherche: (profilId: number, nom: string, getToken?: GetToken) =>
    req<Profil>(`/recherches/${profilId}/sauvegarder`, {
      method: "POST", body: { nom }, getToken }),

  renommerRecherche: (profilId: number, nom: string, getToken?: GetToken) =>
    req<Profil>(`/recherches/${profilId}`, { method: "PUT", body: { nom }, getToken }),

  statutMatching: (jobId: string, getToken?: GetToken) =>
    req<JobStatus>(`/matching/status/${jobId}`, { getToken }),

  matchings: (profilId: number, getToken?: GetToken) =>
    req<Matching[]>(`/matchings/${profilId}`, { getToken }),

  resume: (profilId: number, getToken?: GetToken) =>
    req<Resume>(`/matchings/${profilId}/resume`, { getToken }),

  derniereMaj: () => req<DerniereMaj>("/derniere-maj"),

  // Tout le dashboard en UN appel (résumé + correspondances + fraîcheur).
  dashboard: (profilId: number, getToken?: GetToken) =>
    req<DashboardData>(`/dashboard/${profilId}`, { getToken }),

  detail: (matchingId: number, getToken?: GetToken) =>
    req<MatchingDetail>(`/matching-detail/${matchingId}`, { getToken }),

  sources: () => req<Source[]>("/sources"),

  sourcesRegistry: () =>
    req<{ sources: RegistreEntry[]; comptes: Record<string, number> }>("/sources/registry"),

  // --- Admin ---
  // Toujours 200 : dit simplement si le compte courant est admin.
  suisJeAdmin: (getToken?: GetToken) =>
    req<{ admin: boolean }>("/admin/moi", { getToken }),

  scrapeRuns: (getToken?: GetToken) =>
    req<ScrapeRun[]>("/admin/scrape-runs", { getToken }),

  sourcesSante: (getToken?: GetToken) =>
    req<SourceSante[]>("/admin/sources-sante", { getToken }),

  lancerScrape: (getToken?: GetToken) =>
    req<{ job_id: string }>("/scrape", { method: "POST", getToken }),

  statutScrape: (jobId: string, getToken?: GetToken) =>
    req<{
      statut: string; source_en_cours: string | null; fiches_traitees: number;
      fiches_total_estime: number; erreurs: string[];
      rapport: { total_nouveaux?: number; total_modifies?: number; total_echecs?: number;
                 cout_estime_usd?: number; duree_secondes?: number } | null;
    }>(`/status/${jobId}`, { getToken }),

  subsides: (params: string, getToken?: GetToken) =>
    req<Record<string, unknown>[]>(`/subsides${params}`, { getToken }),

  // --- Candidatures (lot 7, étage 3) ---
  creerCandidature: (body: { profil_id: number; subside_id: number; matching_id?: number },
                     getToken?: GetToken) =>
    req<Candidature>("/candidatures", { method: "POST", body, getToken }),

  // Mémoire (lot 10C) : repartir du dossier de l'édition précédente.
  repartirDossier: (body: { profil_id: number; subside_id: number;
                            ancienne_candidature_id: number; matching_id?: number },
                    getToken?: GetToken) =>
    req<Candidature>("/candidatures/repartir", { method: "POST", body, getToken }),

  candidatures: (profilId: number, getToken?: GetToken) =>
    req<{ candidatures: Candidature[]; stats: CandidatureStats }>(
      `/candidatures/${profilId}`, { getToken }),

  candidature: (id: number, getToken?: GetToken) =>
    req<CandidatureDetail>(`/candidature/${id}`, { getToken }),

  majCandidature: (id: number, body: Partial<{
    statut: StatutCandidature; montant_demande: string | number | null;
    montant_obtenu: string | number | null; date_soumission: string | null;
    date_decision: string | null; notes: string | null;
  }>, getToken?: GetToken) =>
    req<Candidature>(`/candidature/${id}`, { method: "PUT", body, getToken }),

  supprimerCandidature: (id: number, getToken?: GetToken) =>
    req<{ supprime: boolean }>(`/candidature/${id}`, { method: "DELETE", getToken }),

  // Checklist
  genererChecklist: (id: number, forcer = false, getToken?: GetToken) =>
    req<ChecklistEtat>(`/candidature/${id}/checklist`, {
      method: "POST", body: { forcer }, getToken }),

  cocherItem: (itemId: number, coche: boolean, getToken?: GetToken) =>
    req<{ ok: boolean }>(`/checklist-item/${itemId}`, {
      method: "PATCH", body: { coche }, getToken }),

  ajouterItem: (id: number, intitule: string, getToken?: GetToken) =>
    req<ChecklistItem>(`/candidature/${id}/checklist/item`, {
      method: "POST", body: { intitule }, getToken }),

  supprimerItem: (itemId: number, getToken?: GetToken) =>
    req<{ supprime: boolean }>(`/checklist-item/${itemId}`, {
      method: "DELETE", getToken }),

  // Conformité
  verifierConformite: (id: number, description: string, getToken?: GetToken) =>
    req<Conformite>(`/candidature/${id}/conformite`, {
      method: "POST", body: { description }, getToken }),

  // Copilote
  copilote: (id: number, action: string, entree: string, getToken?: GetToken) =>
    req<{ action: string; sortie: string; note: string; erreur?: string }>(
      `/candidature/${id}/copilote`, {
        method: "POST", body: { action, entree }, getToken }),

  // Obligations post-octroi (lot 10B)
  obligationsProfil: (profilId: number, getToken?: GetToken) =>
    req<{ echeances: ObligationEcheance[] }>(`/obligations/${profilId}`, { getToken }),

  genererObligations: (id: number, forcer = false, getToken?: GetToken) =>
    req<ObligationsEtat>(`/candidature/${id}/obligations`, {
      method: "POST", body: { forcer }, getToken }),

  ancrerObligations: (id: number, date_fin_projet: string | null, getToken?: GetToken) =>
    req<ObligationsEtat>(`/candidature/${id}/obligations/ancrage`, {
      method: "POST", body: { date_fin_projet }, getToken }),

  ajouterObligation: (id: number, intitule: string, echeance: string | null,
                      type: string, getToken?: GetToken) =>
    req<Obligation>(`/candidature/${id}/obligations/item`, {
      method: "POST", body: { intitule, echeance, type }, getToken }),

  majObligation: (obligationId: number,
                  body: Partial<{ fait: boolean; intitule: string; echeance: string | null; type: string }>,
                  getToken?: GetToken) =>
    req<Obligation | { ok: boolean }>(`/obligation/${obligationId}`, {
      method: "PATCH", body, getToken }),

  supprimerObligation: (obligationId: number, getToken?: GetToken) =>
    req<{ supprime: boolean }>(`/obligation/${obligationId}`, { method: "DELETE", getToken }),
};

export type {
  DashboardData, DerniereMaj, JobStatus, Matching, MatchingDetail, Profil,
  ProfilInput, Resume, ScrapeRun, Source, SourceSante,
};
