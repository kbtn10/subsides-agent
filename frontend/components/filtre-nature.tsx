"use client";

import { cn } from "@/lib/utils";
import { NATURE_COURT, NATURES, type Nature } from "@/lib/nature";
import type { Matching } from "@/lib/types";

// Filtre par nature de subside — même grammaire visuelle que le filtre de
// pertinence. Partagé par le dashboard (principal + recherche) et la Recherche
// libre.
export type FiltreNat = "toutes" | Nature;

export function filtrerParNature(items: Matching[], filtre: FiltreNat): Matching[] {
  return filtre === "toutes" ? items : items.filter((m) => m.subside.nature === filtre);
}

function Pastille({ label, nombre, actif, onClick }: {
  label: string; nombre: number; actif: boolean; onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick} aria-pressed={actif}
      className={cn(
        "rounded-full border px-2.5 py-1 text-[13px] transition-colors",
        actif
          ? "border-accent bg-accent-soft font-medium text-accent"
          : "border-border text-ink-soft hover:bg-surface-2 hover:text-ink",
      )}>
      {label} <span className={actif ? "text-accent/70" : "text-ink-faint"}>{nombre}</span>
    </button>
  );
}

/** N'apparaît que si au moins deux natures distinctes sont présentes (sinon il
 *  n'y a rien à filtrer). Les natures absentes sont masquées. */
export function FiltreNature({ eligibles, valeur, onChange }: {
  eligibles: Matching[]; valeur: FiltreNat; onChange: (v: FiltreNat) => void;
}) {
  const comptes: Record<Nature, number> = {
    appel_a_projets: 0, dispositif_permanent: 0, prix_concours: 0, financement_instrument: 0,
  };
  eligibles.forEach((m) => {
    const n = m.subside.nature;
    if (n && n in comptes) comptes[n]++;
  });
  const presentes = NATURES.filter((n) => comptes[n] > 0);
  if (presentes.length < 2) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filtrer par nature">
      <span className="mr-0.5 text-[13px] text-ink-faint">Nature</span>
      <Pastille label="Toutes" nombre={eligibles.length}
        actif={valeur === "toutes"} onClick={() => onChange("toutes")} />
      {presentes.map((n) => (
        <Pastille key={n} label={NATURE_COURT[n]} nombre={comptes[n]}
          actif={valeur === n} onClick={() => onChange(n)} />
      ))}
    </div>
  );
}
