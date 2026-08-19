"use client";

import type { LucideIcon } from "lucide-react";
import { AnimatedNumber } from "./animated-number";

type Teinte = "accent" | "amber" | "neutral" | "info";

// La pastille d'icône : fond très léger, icône dans le ton fort. La couleur
// SIGNIFIE (correspondances = vert, échéances = ambre…), jamais décorative.
const PASTILLE: Record<Teinte, string> = {
  accent: "bg-accent-soft text-accent",
  amber: "bg-amber-soft text-amber",
  neutral: "bg-neutral-soft text-neutral",
  info: "bg-info-soft text-info",
};

/** Tuile de stat : chiffre en Fraunces dominant + pastille d'icône teintée. */
export function StatTile({
  valeur, libelle, sousTexte, texte, accent = false, icon: Icon, teinte = "neutral",
}: {
  valeur?: number; libelle: string; sousTexte?: string; texte?: string;
  accent?: boolean; icon?: LucideIcon; teinte?: Teinte;
}) {
  return (
    <div className="rounded-[var(--radius-card)] border border-border bg-surface px-4 py-3.5">
      <div className="flex items-start justify-between gap-2">
        <p className={`font-display text-2xl font-semibold leading-none ${accent ? "text-accent" : "text-ink"}`}>
          {texte !== undefined ? texte : <AnimatedNumber value={valeur ?? 0} />}
        </p>
        {Icon && (
          <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${PASTILLE[teinte]}`}>
            <Icon className="h-4 w-4" aria-hidden />
          </span>
        )}
      </div>
      <p className="mt-1.5 text-[13px] leading-snug text-ink-soft">{libelle}</p>
      {sousTexte && <p className="mt-0.5 text-[12px] text-ink-faint">{sousTexte}</p>}
    </div>
  );
}
