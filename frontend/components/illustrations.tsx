/**
 * Illustrations d'états vides — SVG MAISON (lot 8), 2-4 formes simples chacune,
 * aucune dépendance, aucune image stock. Les couleurs héritent des variables du
 * design system via `currentColor` (posé par la classe de couleur du parent) et
 * les tokens `--accent` / `--amber`. Décoratives mais dans la palette.
 */

const V = "var(--accent)";
const A = "var(--amber)";

/** Radar : cercles concentriques + point qui capte (dashboard sans correspondance). */
export function IllusRadar({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 96 96" className={className} fill="none" aria-hidden>
      <circle cx="48" cy="48" r="34" stroke="var(--border-strong)" strokeWidth="2" />
      <circle cx="48" cy="48" r="22" stroke="var(--border-strong)" strokeWidth="2" />
      <circle cx="48" cy="48" r="10" stroke="var(--border-strong)" strokeWidth="2" />
      <path d="M48 48 L48 14" stroke={V} strokeWidth="2.5" strokeLinecap="round" />
      <path d="M48 48 L74 60" stroke={V} strokeWidth="2.5" strokeLinecap="round" opacity="0.35" />
      <circle cx="66" cy="34" r="4.5" fill={V} />
      <circle cx="48" cy="48" r="3" fill={V} />
    </svg>
  );
}

/** Calendrier apaisé (échéances vide). */
export function IllusCalendrier({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 96 96" className={className} fill="none" aria-hidden>
      <rect x="18" y="22" width="60" height="54" rx="8" stroke="var(--border-strong)" strokeWidth="2" />
      <path d="M18 36 H78" stroke="var(--border-strong)" strokeWidth="2" />
      <path d="M32 16 V28 M64 16 V28" stroke={V} strokeWidth="2.5" strokeLinecap="round" />
      <path d="M36 56 l7 7 14 -16" stroke={V} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Dossier ouvert (candidatures vide). */
export function IllusDossier({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 96 96" className={className} fill="none" aria-hidden>
      <path d="M20 30 h20 l6 8 h30 a4 4 0 0 1 4 4 v6 H16 v-24 a4 4 0 0 1 4 -4Z"
        stroke="var(--border-strong)" strokeWidth="2" strokeLinejoin="round" />
      <path d="M16 50 h64 l-6 24 a4 4 0 0 1 -4 3 H22 a4 4 0 0 1 -4 -3Z"
        fill="var(--accent-soft)" stroke={V} strokeWidth="2" strokeLinejoin="round" />
      <path d="M48 42 v-8 M44 38 h8" stroke={A} strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

/** Loupe (recherche libre avant première recherche). */
export function IllusLoupe({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 96 96" className={className} fill="none" aria-hidden>
      <circle cx="42" cy="42" r="22" stroke="var(--border-strong)" strokeWidth="2.5" />
      <path d="M58 58 L74 74" stroke={V} strokeWidth="3.5" strokeLinecap="round" />
      <path d="M34 42 a8 8 0 0 1 8 -8" stroke={V} strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}
