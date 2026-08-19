// Nom du produit — placeholder, isolé pour un renommage facile plus tard.
export const PRODUCT_NAME = "Subsidia";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Région du siège (lot 6) : pilote les subsides éligibles au matching.
export const REGIONS: { value: string; label: string }[] = [
  { value: "bruxelles", label: "Région bruxelloise" },
  { value: "wallonie", label: "Wallonie" },
];

export const COMMUNES_19 = [
  "Anderlecht", "Auderghem", "Berchem-Sainte-Agathe", "Bruxelles-Ville",
  "Etterbeek", "Evere", "Forest", "Ganshoren", "Ixelles", "Jette",
  "Koekelberg", "Molenbeek-Saint-Jean", "Saint-Gilles", "Saint-Josse-ten-Noode",
  "Schaerbeek", "Uccle", "Watermael-Boitsfort", "Woluwe-Saint-Lambert",
  "Woluwe-Saint-Pierre",
];

// La Wallonie compte 262 communes : une liste déroulante serait illisible. La
// province suffit au contexte (le matching, lui, ne dépend que de la région).
export const PROVINCES_WALLONNES = [
  "Brabant wallon", "Hainaut", "Liège", "Luxembourg", "Namur",
];

export const SECTEURS: { value: string; label: string }[] = [
  { value: "culture", label: "Culture" },
  { value: "jeunesse", label: "Jeunesse" },
  { value: "sport", label: "Sport" },
  { value: "social_sante", label: "Social / Santé" },
  { value: "cohesion_sociale", label: "Cohésion sociale" },
  { value: "education_permanente", label: "Éducation permanente" },
  { value: "egalite_chances", label: "Égalité des chances" },
  { value: "environnement", label: "Environnement" },
  { value: "cooperation", label: "Coopération" },
  { value: "media", label: "Média" },
  { value: "recherche", label: "Recherche" },
  { value: "autre", label: "Autre" },
];

export const LANGUES: { value: string; label: string }[] = [
  { value: "fr", label: "Français" },
  { value: "nl", label: "Néerlandais" },
  { value: "bilingue", label: "Bilingue" },
];

export const BUDGETS: { value: string; label: string }[] = [
  { value: "moins_50k", label: "Moins de 50 000 €" },
  { value: "50k_250k", label: "50 000 – 250 000 €" },
  { value: "250k_1M", label: "250 000 € – 1 M€" },
  { value: "plus_1M", label: "Plus d'1 M€" },
  { value: "inconnu", label: "Je ne sais pas" },
];

// Libellés « humains » des verdicts — jamais de jargon technique à l'écran.
export const VERDICT_LABEL: Record<string, string> = {
  probablement_eligible: "Probablement éligible",
  eligible_sous_conditions: "Sous conditions",
  non_eligible: "Non retenu",
  erreur: "À réessayer",
};

// Statuts de candidature (lot 7). Ordre = ordre des colonnes du tableau.
export const STATUTS_CANDIDATURE = [
  "a_etudier", "dossier_en_cours", "soumis", "obtenu", "refuse",
] as const;

export const STATUT_LABEL: Record<string, string> = {
  a_etudier: "À étudier",
  dossier_en_cours: "Dossier en cours",
  soumis: "Soumis",
  obtenu: "Obtenu",
  refuse: "Refusé",
  abandonne: "Abandonné",
};

// Pastille de couleur par statut (design system, lot 8). La couleur signifie
// l'avancement : gris (à étudier) → ambre (en cours) → bleu-gris (soumis, en
// attente) → vert (obtenu) ; refusé/abandonné en gris estompé.
export const STATUT_STYLE: Record<string, string> = {
  a_etudier: "bg-surface-2 text-ink-soft",
  dossier_en_cours: "bg-amber-soft text-amber",
  soumis: "bg-info-soft text-info",
  obtenu: "bg-accent-soft text-accent",
  refuse: "bg-neutral-soft text-neutral",
  abandonne: "bg-neutral-soft text-neutral",
};
