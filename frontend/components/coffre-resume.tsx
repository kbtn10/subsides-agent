"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useCoffreActif } from "@/lib/use-coffre";
import type { CoffreEtat } from "@/lib/types";

/** Ligne discrète du dashboard : état du coffre (lot 10A). Rien si flag off. */
export function CoffreResume({ profilId }: { profilId: number }) {
  const { getToken } = useAuth();
  const actif = useCoffreActif();
  const [etat, setEtat] = useState<CoffreEtat | null>(null);

  useEffect(() => {
    if (!actif) return;
    api.coffre(profilId, getToken).then(setEtat).catch(() => {});
  }, [actif, profilId, getToken]);

  if (!actif || !etat || etat.total === 0) return null;

  return (
    <Link href="/coffre"
      className="mb-5 flex items-center gap-2 rounded-[var(--radius-card)] border border-border bg-surface-2 px-4 py-2.5 text-sm text-ink-soft transition-shadow hover:shadow-[var(--shadow-lift)]">
      <ShieldCheck className="h-4 w-4 shrink-0 text-accent" aria-hidden />
      <span>
        Coffre : <span className="font-medium text-ink">{etat.a_jour} document{etat.a_jour > 1 ? "s" : ""} à jour</span>
        {etat.a_renouveler > 0 && <> · <span className="font-medium text-amber">{etat.a_renouveler} à renouveler</span></>}
      </span>
    </Link>
  );
}
