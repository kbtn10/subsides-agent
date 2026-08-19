"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { ArrowLeft, ArrowUpRight, History, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BadgeEcheance } from "@/components/compact-card";
import { ChecklistSection } from "@/components/candidature/checklist-section";
import { ConformiteSection } from "@/components/candidature/conformite-section";
import { CopiloteSection } from "@/components/candidature/copilote-section";
import { api, ApiError } from "@/lib/api";
import { STATUT_LABEL, STATUT_STYLE } from "@/lib/constants";
import type { CandidatureDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useTitre } from "@/lib/use-titre";

export default function CandidaturePage() {
  useTitre("Ma candidature");
  const params = useParams<{ id: string }>();
  const { getToken } = useAuth();
  const id = Number(params?.id);
  const idValide = Number.isInteger(id) && id > 0;

  const [c, setC] = useState<CandidatureDetail | null>(null);
  const [etat, setEtat] = useState<"chargement" | "ok" | "introuvable" | "erreur">("chargement");

  useEffect(() => {
    if (!idValide) return;
    api.candidature(id, getToken)
      .then((d) => { setC(d); setEtat("ok"); })
      .catch((e) => setEtat(e instanceof ApiError && (e.status === 404 || e.status === 403)
        ? "introuvable" : "erreur"));
  }, [id, idValide, getToken]);

  if (!idValide || etat === "introuvable" || etat === "erreur") {
    return (
      <div className="py-16 text-center">
        <h1 className="font-display text-2xl font-semibold text-ink">
          {etat === "erreur" ? "Impossible d'afficher cette candidature" : "Candidature introuvable"}
        </h1>
        <Link href="/candidatures" className="mt-5 inline-block">
          <Button variant="ghost"><ArrowLeft className="h-4 w-4" /> Mes candidatures</Button>
        </Link>
      </div>
    );
  }
  if (etat === "chargement" || !c) {
    return <p className="flex items-center gap-2 py-10 text-ink-soft">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Chargement…
    </p>;
  }

  const s = c.subside;
  const rec = c.recurrence;

  return (
    <div>
      <Link href="/candidatures"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-soft hover:text-ink">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Mes candidatures
      </Link>

      <header className="mt-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("rounded-full px-2.5 py-1 text-[11px] font-bold", STATUT_STYLE[c.statut])}>
            {STATUT_LABEL[c.statut]}
          </span>
          <BadgeEcheance deadline={s?.deadline ?? null} permanent={Boolean(s?.permanent)} />
        </div>
        <h1 className="mt-2.5 font-display text-[26px] font-semibold leading-tight text-ink">
          {s?.titre ?? "Candidature"}
        </h1>
        <p className="mt-1.5 text-ink-soft">
          {(s?.organisme as string) ?? s?.source_id}
          {s?.montant ? <span className="text-ink-faint"> · {String(s.montant)}</span> : null}
        </p>

        {rec && (
          <p className="mt-3 flex items-center gap-2 rounded-[var(--radius-ctrl)] bg-info-soft px-3 py-2 text-sm text-info">
            <History className="h-4 w-4 shrink-0" aria-hidden />
            Cet appel semble récurrent — édition {rec.annee} détectée les années précédentes.
          </p>
        )}

        <div className="mt-4 flex flex-wrap gap-3">
          {s?.url_source ? (
            <a href={String(s.url_source)} target="_blank" rel="noopener noreferrer">
              <Button variant="ghost" size="sm">Fiche officielle <ArrowUpRight className="h-4 w-4" /></Button>
            </a>
          ) : null}
          {s?.lien_candidature && s.lien_candidature !== s.url_source ? (
            <a href={String(s.lien_candidature)} target="_blank" rel="noopener noreferrer">
              <Button size="sm">Déposer sur la plateforme officielle <ArrowUpRight className="h-4 w-4" /></Button>
            </a>
          ) : null}
        </div>
        <p className="mt-3 text-[13px] text-ink-faint">
          Subsidia vous accompagne mais ne soumet rien : le dépôt se fait sur la
          plateforme officielle, et vous restez l&apos;auteur du dossier.
        </p>
      </header>

      <div className="mt-6 space-y-5">
        <ChecklistSection candidatureId={c.id} initial={c.checklist} />
        <ConformiteSection candidatureId={c.id} />
        <CopiloteSection candidatureId={c.id} historique={c.copilote} />
      </div>
    </div>
  );
}
