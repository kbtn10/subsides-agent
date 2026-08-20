"use client";

import Link from "next/link";
import { motion, useReducedMotion } from "framer-motion";
import { AlertTriangle, RotateCw } from "lucide-react";
import type { Matching } from "@/lib/types";
import { VERDICT_LABEL } from "@/lib/constants";
import { NatureBadge } from "@/components/nature-badge";
import { cn } from "@/lib/utils";

export function joursAvant(deadline: string | null): number | null {
  if (!deadline) return null;
  return Math.ceil((new Date(deadline).getTime() - Date.now()) / 86_400_000);
}

const barre: Record<string, string> = {
  probablement_eligible: "before:bg-accent",
  eligible_sous_conditions: "before:bg-amber",
  non_eligible: "before:bg-neutral",
  erreur: "before:bg-neutral",
};

export const pastille: Record<string, string> = {
  probablement_eligible: "bg-accent-soft text-accent",
  eligible_sous_conditions: "bg-amber-soft text-amber",
  non_eligible: "bg-neutral-soft text-neutral",
  erreur: "bg-neutral-soft text-neutral",
};

/** Badge d'échéance : J-n, ambre si < 30 jours. */
export function BadgeEcheance({ deadline, permanent }: { deadline: string | null; permanent?: boolean }) {
  const j = joursAvant(deadline);
  if (!deadline) {
    return <span className="rounded-md bg-surface-2 px-2 py-0.5 text-[12px] text-ink-soft">
      {permanent ? "En continu" : "Sans échéance"}
    </span>;
  }
  const urgent = j !== null && j >= 0 && j < 30;
  return (
    <span className={cn("rounded-md px-2 py-0.5 text-[12px] font-semibold",
      urgent ? "bg-amber-soft text-amber" : "bg-surface-2 text-ink-soft")}>
      {j !== null && j >= 0 ? `J-${j}` : "Échéance passée"}
    </span>
  );
}

/**
 * Carte compacte et scannable : tout l'essentiel en une ligne de regard.
 * Le détail complet vit sur /subside/{id}. Toute la carte est un lien (donc
 * navigable au clavier, focus visible, deep-link partageable).
 */
export function CompactCard({
  m, index = 0, onRetry,
}: { m: Matching; index?: number; onRetry?: () => void }) {
  const reduce = useReducedMotion();
  const s = m.subside;
  const nbAVerifier = m.criteres_a_verifier?.length ?? 0;

  // Carte d'échec : jamais de code technique, une action claire.
  if (m.verdict === "erreur") {
    return (
      <motion.div
        initial={reduce ? false : { opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: reduce ? 0 : Math.min(index * 0.08, 0.8) }}
        className="flex h-full flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border border-border bg-surface-2 px-4 py-3.5"
      >
        <div className="min-w-0">
          <p className="truncate font-medium text-ink">{s.titre}</p>
          <p className="text-sm text-ink-soft">L&apos;analyse a échoué pour ce subside.</p>
        </div>
        {onRetry && (
          <button onClick={onRetry}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-ctrl)] border border-border-strong px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface">
            <RotateCw className="h-3.5 w-3.5" aria-hidden /> Réessayer
          </button>
        )}
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut", delay: reduce ? 0 : Math.min(index * 0.08, 0.8) }}
      whileHover={reduce ? undefined : { y: -2 }}
      className="h-full"
    >
      <Link
        href={`/subside/${m.id}`}
        className={cn(
          "relative flex h-full flex-col overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface p-4 shadow-[var(--shadow-soft)] transition-shadow hover:shadow-[var(--shadow-lift)]",
          "before:absolute before:left-0 before:top-0 before:h-full before:w-1",
          barre[m.verdict],
        )}
      >
        <div className="flex items-start justify-between gap-3 pl-1.5">
          {/* Deux lignes max plutôt qu'une troncature sèche : sur 375px, un
              titre coupé au 3e mot ne dit plus rien. Le min-h réserve TOUJOURS
              la hauteur de deux lignes : un titre court occupe le même espace
              qu'un titre long, ce qui aligne les cartes d'une même rangée. */}
          <h3 title={s.titre}
            className="line-clamp-2 min-h-[2.75em] font-display text-[17px] font-semibold leading-snug text-ink">
            {s.titre}
          </h3>
          <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold", pastille[m.verdict])}>
            {VERDICT_LABEL[m.verdict]}
          </span>
        </div>
        {/* mt-auto : la rangée méta est ancrée en bas, alignée d'une carte à
            l'autre quelle que soit la longueur du titre. */}
        <div className="mt-auto flex flex-wrap items-center gap-x-2.5 gap-y-1.5 pt-2 pl-1.5 text-[13px] text-ink-soft">
          <span className="truncate">{s.organisme ?? s.source_id}</span>
          <span className="text-ink-faint">·</span>
          <BadgeEcheance deadline={s.deadline} permanent={s.permanent} />
          <NatureBadge nature={s.nature} />
          {m.pertinence && <span className="text-ink-faint">pertinence {m.pertinence}</span>}
          {nbAVerifier > 0 && (
            <span className="inline-flex items-center gap-1 text-amber">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
              {nbAVerifier} point{nbAVerifier > 1 ? "s" : ""} à vérifier
            </span>
          )}
        </div>
      </Link>
    </motion.div>
  );
}
