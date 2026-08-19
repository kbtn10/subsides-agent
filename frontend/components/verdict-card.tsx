"use client";

import { motion, useReducedMotion } from "framer-motion";
import { AlertTriangle, ArrowUpRight, Check, ChevronRight } from "lucide-react";
import type { Matching } from "@/lib/types";
import { VERDICT_LABEL } from "@/lib/constants";
import { cn } from "@/lib/utils";

function joursAvant(deadline: string | null): number | null {
  if (!deadline) return null;
  const ms = new Date(deadline).getTime() - Date.now();
  return Math.ceil(ms / 86_400_000);
}

const accentBar: Record<string, string> = {
  probablement_eligible: "before:bg-accent",
  eligible_sous_conditions: "before:bg-amber",
  non_eligible: "before:bg-neutral",
  erreur: "before:bg-danger",
};

const pastille: Record<string, string> = {
  probablement_eligible: "bg-accent-soft text-accent",
  eligible_sous_conditions: "bg-amber-soft text-amber",
  non_eligible: "bg-neutral-soft text-neutral",
  erreur: "bg-[#f7e6e2] text-danger",
};

export function VerdictCard({ m, index = 0 }: { m: Matching; index?: number }) {
  const reduce = useReducedMotion();
  const s = m.subside;
  const j = joursAvant(s.deadline);
  const urgent = j !== null && j >= 0 && j < 30;

  return (
    <motion.article
      initial={reduce ? false : { opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.42, ease: "easeOut", delay: reduce ? 0 : Math.min(index * 0.08, 0.8) }}
      whileHover={reduce ? undefined : { y: -2 }}
      className={cn(
        "relative overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface p-5 shadow-[var(--shadow-soft)]",
        "before:absolute before:left-0 before:top-0 before:h-full before:w-1",
        accentBar[m.verdict],
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-display text-lg font-semibold leading-snug text-ink">
          <a
            href={s.url_source}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline"
          >
            {s.titre}
          </a>
        </h3>
        <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-xs font-bold", pastille[m.verdict])}>
          {VERDICT_LABEL[m.verdict] ?? m.verdict}
        </span>
      </div>

      <p className="mt-1 text-sm text-ink-soft">
        {s.organisme ?? s.source_id}
        {s.montant ? <span className="text-ink-faint"> · {s.montant}</span> : null}
      </p>

      <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[13px]">
        {s.deadline ? (
          <span
            className={cn(
              "inline-flex items-center rounded-md px-2 py-0.5 font-semibold",
              urgent ? "bg-amber-soft text-amber" : "bg-surface-2 text-ink-soft",
            )}
          >
            {j !== null && j >= 0 ? `J-${j}` : "Échéance passée"}
            <span className="ml-1.5 font-normal">· {s.deadline}</span>
          </span>
        ) : (
          <span className="rounded-md bg-surface-2 px-2 py-0.5 text-ink-soft">
            {s.permanent ? "En continu" : "Échéance non précisée"}
          </span>
        )}
        {m.pertinence && (
          <span className="text-ink-faint">Pertinence {m.pertinence}</span>
        )}
      </div>

      {m.justification && (
        <p className="mt-3 text-[15px] leading-relaxed text-ink/90">{m.justification}</p>
      )}

      {m.criteres_a_verifier.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
            À vérifier avant de candidater
          </p>
          <ul className="mt-1.5 space-y-1">
            {m.criteres_a_verifier.map((c, i) => (
              <li key={i} className="flex gap-2 text-sm text-ink/90">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber" aria-hidden />
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {m.verdict === "probablement_eligible" && m.criteres_satisfaits.length > 0 && (
        <ul className="mt-3 space-y-1">
          {m.criteres_satisfaits.slice(0, 2).map((c, i) => (
            <li key={i} className="flex gap-2 text-sm text-ink-soft">
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
              <span>{c}</span>
            </li>
          ))}
        </ul>
      )}

      {m.criteres_non_satisfaits.length > 0 && (
        <ul className="mt-3 space-y-1">
          {m.criteres_non_satisfaits.map((c, i) => (
            <li key={i} className="flex gap-2 text-sm text-neutral">
              <ChevronRight className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>{c}</span>
            </li>
          ))}
        </ul>
      )}

      <a
        href={s.url_source}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-accent hover:text-accent-hover"
      >
        Voir la fiche officielle
        <ArrowUpRight className="h-4 w-4" aria-hidden />
      </a>
    </motion.article>
  );
}
