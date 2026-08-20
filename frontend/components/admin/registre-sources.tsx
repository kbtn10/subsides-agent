"use client";

import { useEffect, useMemo, useState } from "react";
import { ExternalLink } from "lucide-react";
import { Select } from "@/components/ui/field";
import { api } from "@/lib/api";
import type { RegistreEntry, StatutRegistre } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUT_LABEL: Record<StatutRegistre, string> = {
  active: "Active", a_evaluer: "À évaluer", differee: "Différée", ecartee: "Écartée",
};
const STATUT_STYLE: Record<StatutRegistre, string> = {
  active: "bg-accent-soft text-accent",
  a_evaluer: "bg-amber-soft text-amber",
  differee: "bg-info-soft text-info",
  ecartee: "bg-neutral-soft text-neutral",
};

/** Registre des sources (lot 9) : couverture visible et honnête. */
export function RegistreSources() {
  const [rows, setRows] = useState<RegistreEntry[]>([]);
  const [comptes, setComptes] = useState<Record<string, number>>({});
  const [fStatut, setFStatut] = useState("");
  const [fNiveau, setFNiveau] = useState("");

  useEffect(() => {
    api.sourcesRegistry().then((d) => { setRows(d.sources); setComptes(d.comptes); }).catch(() => {});
  }, []);

  const niveaux = useMemo(
    () => Array.from(new Set(rows.map((r) => r.niveau).filter(Boolean))) as string[], [rows]);
  const visibles = rows.filter((r) =>
    (!fStatut || r.statut === fStatut) && (!fNiveau || r.niveau === fNiveau));

  if (!rows.length) return null;

  return (
    <section className="rounded-[var(--radius-card)] border border-border bg-surface p-5 shadow-[var(--shadow-soft)]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-lg font-semibold text-ink">Registre des sources</h2>
        <p className="text-sm text-ink-soft">
          <span className="font-semibold text-accent">{comptes.active ?? 0} actives</span>
          {" / "}{comptes.total ?? rows.length} identifiées
        </p>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Select value={fStatut} onChange={(e) => setFStatut(e.target.value)} className="w-auto">
          <option value="">Tous statuts</option>
          {(["active", "a_evaluer", "differee", "ecartee"] as StatutRegistre[]).map((s) => (
            <option key={s} value={s}>{STATUT_LABEL[s]} ({comptes[s] ?? 0})</option>
          ))}
        </Select>
        <Select value={fNiveau} onChange={(e) => setFNiveau(e.target.value)} className="w-auto">
          <option value="">Tous niveaux</option>
          {niveaux.map((n) => <option key={n} value={n}>{n}</option>)}
        </Select>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[12px] uppercase tracking-wide text-ink-faint">
              <th className="pb-2 pr-3 font-semibold">Source</th>
              <th className="pb-2 pr-3 font-semibold">Niveau</th>
              <th className="pb-2 pr-3 font-semibold">Statut</th>
              <th className="pb-2 pr-3 font-semibold">Raison</th>
              <th className="pb-2 font-semibold">Lien</th>
            </tr>
          </thead>
          <tbody>
            {visibles.map((r) => (
              <tr key={r.id} className="border-b border-border/60 align-top">
                <td className="py-2.5 pr-3 font-medium text-ink">{r.nom}</td>
                <td className="py-2.5 pr-3 text-ink-soft">{r.niveau ?? "—"}</td>
                <td className="py-2.5 pr-3">
                  <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-bold",
                    STATUT_STYLE[r.statut])}>{STATUT_LABEL[r.statut]}</span>
                </td>
                <td className="py-2.5 pr-3 text-[13px] leading-snug text-ink-soft">{r.raison ?? "—"}</td>
                <td className="py-2.5">
                  {r.url_entree ? (
                    <a href={r.url_entree} target="_blank" rel="noopener noreferrer"
                      className="text-accent hover:underline" aria-label={`Ouvrir ${r.nom}`}>
                      <ExternalLink className="h-4 w-4" aria-hidden />
                    </a>
                  ) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
