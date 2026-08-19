"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { BellRing, Clock } from "lucide-react";
import { api } from "@/lib/api";
import { joursAvant } from "@/components/compact-card";
import type { Candidature } from "@/lib/types";

function joursDepuis(iso: string | null): number | null {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}

/**
 * Rappels de candidatures en cours, affichés en tête du dashboard et des
 * échéances (lot 7) :
 *   - dossier_en_cours dont la deadline est < 14 j -> alerte
 *   - soumis sans décision depuis 90 j -> relance douce « des nouvelles ? »
 */
export function RappelsCandidatures({ profilId }: { profilId: number }) {
  const { getToken } = useAuth();
  const [liste, setListe] = useState<Candidature[]>([]);

  useEffect(() => {
    api.candidatures(profilId, getToken)
      .then((d) => setListe(d.candidatures))
      .catch(() => {});
  }, [profilId, getToken]);

  const urgents = liste.filter((c) => {
    if (c.statut !== "dossier_en_cours" || !c.subside?.deadline) return false;
    const j = joursAvant(c.subside.deadline);
    return j !== null && j >= 0 && j < 14;
  });
  const relances = liste.filter((c) => {
    if (c.statut !== "soumis") return false;
    const j = joursDepuis(c.date_soumission);
    return j !== null && j >= 90;
  });

  if (!urgents.length && !relances.length) return null;

  return (
    <div className="mb-5 space-y-2">
      {urgents.map((c) => {
        const j = joursAvant(c.subside!.deadline)!;
        return (
          <Link key={c.id} href={`/candidature/${c.id}`}
            className="flex items-center gap-2.5 rounded-[var(--radius-card)] border border-amber/40 bg-amber-soft px-4 py-3 text-sm text-amber transition-shadow hover:shadow-[var(--shadow-lift)]">
            <BellRing className="h-4 w-4 shrink-0" aria-hidden />
            <span>
              Dossier en cours — <span className="font-semibold">{c.subside!.titre}</span> :
              échéance dans {j === 0 ? "moins d'un jour" : `${j} jour${j > 1 ? "s" : ""}`}.
            </span>
          </Link>
        );
      })}
      {relances.map((c) => (
        <Link key={c.id} href={`/candidature/${c.id}`}
          className="flex items-center gap-2.5 rounded-[var(--radius-card)] border border-border bg-surface-2 px-4 py-3 text-sm text-ink-soft transition-shadow hover:shadow-[var(--shadow-lift)]">
          <Clock className="h-4 w-4 shrink-0" aria-hidden />
          <span>
            Soumis il y a plus de 3 mois — <span className="font-medium text-ink">{c.subside!.titre}</span> :
            des nouvelles ? Vous pouvez mettre à jour le statut.
          </span>
        </Link>
      ))}
    </div>
  );
}
