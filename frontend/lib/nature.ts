// Métadonnées de la « nature » d'un subside (lot 9). Une seule source de vérité
// pour les libellés, les libellés courts (badges) et les icônes lucide.
import type { LucideIcon } from "lucide-react";
import { Award, Infinity as InfinityIcon, Landmark, Megaphone } from "lucide-react";

export type Nature =
  | "appel_a_projets"
  | "dispositif_permanent"
  | "prix_concours"
  | "financement_instrument";

export const NATURES: Nature[] = [
  "appel_a_projets", "dispositif_permanent", "prix_concours", "financement_instrument",
];

export const NATURE_LABEL: Record<Nature, string> = {
  appel_a_projets: "Appel à projets",
  dispositif_permanent: "Dispositif permanent",
  prix_concours: "Prix / concours",
  financement_instrument: "Prêt / garantie",
};

// Libellé court pour le badge de carte (place limitée).
export const NATURE_COURT: Record<Nature, string> = {
  appel_a_projets: "Appel à projets",
  dispositif_permanent: "Permanent",
  prix_concours: "Prix",
  financement_instrument: "Prêt / garantie",
};

export const NATURE_ICON: Record<Nature, LucideIcon> = {
  appel_a_projets: Megaphone,
  dispositif_permanent: InfinityIcon,
  prix_concours: Award,
  financement_instrument: Landmark,
};

/** Ces natures ne se candidatent pas via un appel formel : pas de checklist
 *  auto, la démarche passe par l'organisme. */
export const NATURE_SANS_APPEL: Nature[] = ["dispositif_permanent", "financement_instrument"];

export function estNature(v: unknown): v is Nature {
  return typeof v === "string" && (NATURES as string[]).includes(v);
}
