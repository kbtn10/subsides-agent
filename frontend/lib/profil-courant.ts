"use client";

import { api } from "./api";

const CLE = "subsidia_profil_id";

type GetToken = () => Promise<string | null>;

/**
 * Résout le profil courant de l'utilisateur, SANS dépendre uniquement du
 * localStorage.
 *
 * Le localStorage n'est qu'un cache d'accès rapide : il se vide dès qu'on change
 * de navigateur, qu'on ouvre une fenêtre privée, qu'on nettoie le cache, ou tout
 * simplement avec le temps. S'y fier seul faisait rebondir l'utilisateur vers
 * l'onboarding alors que son profil existe bel et bien en base, rattaché à son
 * compte Clerk. On interroge donc l'API en repli, et on re-remplit le cache.
 *
 * Renvoie l'id du profil, ou null si l'utilisateur n'a réellement aucun profil
 * (là, l'onboarding est la bonne destination).
 */
export async function resoudreProfilId(getToken: GetToken): Promise<number | null> {
  if (typeof window !== "undefined") {
    const cache = localStorage.getItem(CLE);
    if (cache && Number.isFinite(Number(cache))) return Number(cache);
  }

  // Repli : demander au backend les profils de CE compte Clerk.
  const profils = await api.mesProfils(getToken);
  const p = profils.find((x) => !x.ephemere) ?? profils[0];
  if (!p) return null;

  if (typeof window !== "undefined") localStorage.setItem(CLE, String(p.id));
  return p.id;
}

export function oublierProfilCache() {
  if (typeof window !== "undefined") localStorage.removeItem(CLE);
}
