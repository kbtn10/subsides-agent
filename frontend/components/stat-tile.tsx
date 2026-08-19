"use client";

import { AnimatedNumber } from "./animated-number";

/** Tuile de stat sobre : chiffre en Fraunces, libellé dessous. Pas de gradient. */
export function StatTile({
  valeur, libelle, texte, accent = false,
}: { valeur?: number; libelle: string; texte?: string; accent?: boolean }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-border bg-surface px-4 py-3.5">
      <p className={`font-display text-2xl font-semibold leading-none ${accent ? "text-accent" : "text-ink"}`}>
        {texte !== undefined ? texte : <AnimatedNumber value={valeur ?? 0} />}
      </p>
      <p className="mt-1.5 text-[13px] leading-snug text-ink-soft">{libelle}</p>
    </div>
  );
}
