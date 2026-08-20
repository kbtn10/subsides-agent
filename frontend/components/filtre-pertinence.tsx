"use client";

import { cn } from "@/lib/utils";
import type { Matching } from "@/lib/types";

// Filtre de pertinence partagé par « Mes subsides » (dashboard principal ET
// dashboard d'une recherche) et la Recherche libre. Les correspondances sont
// déjà triées par pertinence décroissante ; ces pastilles isolent un niveau.
export type FiltrePert = "toutes" | "forte" | "moyenne" | "faible";

const NIVEAUX: { valeur: Exclude<FiltrePert, "toutes">; label: string }[] = [
  { valeur: "forte", label: "Forte" },
  { valeur: "moyenne", label: "Moyenne" },
  { valeur: "faible", label: "Faible" },
];

/** Applique le filtre à une liste de correspondances. */
export function filtrerParPertinence(items: Matching[], filtre: FiltrePert): Matching[] {
  return filtre === "toutes" ? items : items.filter((m) => m.pertinence === filtre);
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

/** Barre de pastilles. Ne s'affiche qu'à partir de 2 correspondances ; les
 *  niveaux sans aucune correspondance sont masqués. */
export function FiltrePertinence({ eligibles, valeur, onChange }: {
  eligibles: Matching[]; valeur: FiltrePert; onChange: (v: FiltrePert) => void;
}) {
  if (eligibles.length < 2) return null;
  const comptes: Record<Exclude<FiltrePert, "toutes">, number> = { forte: 0, moyenne: 0, faible: 0 };
  eligibles.forEach((m) => {
    if (m.pertinence && m.pertinence in comptes) comptes[m.pertinence as keyof typeof comptes]++;
  });
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filtrer par pertinence">
      <span className="mr-0.5 text-[13px] text-ink-faint">Pertinence</span>
      <Pastille label="Toutes" nombre={eligibles.length}
        actif={valeur === "toutes"} onClick={() => onChange("toutes")} />
      {NIVEAUX.filter((n) => comptes[n.valeur] > 0).map((n) => (
        <Pastille key={n.valeur} label={n.label} nombre={comptes[n.valeur]}
          actif={valeur === n.valeur} onClick={() => onChange(n.valeur)} />
      ))}
    </div>
  );
}
