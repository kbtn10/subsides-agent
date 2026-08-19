"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { ClipboardList, Loader2, TrendingUp, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BadgeEcheance, joursAvant } from "@/components/compact-card";
import { StatTile } from "@/components/stat-tile";
import { StatutModale } from "@/components/statut-modale";
import { IllusDossier } from "@/components/illustrations";
import { useToast } from "@/components/toast";
import { useTitre } from "@/lib/use-titre";
import { api } from "@/lib/api";
import { resoudreProfilId } from "@/lib/profil-courant";
import { STATUTS_CANDIDATURE, STATUT_LABEL, STATUT_STYLE } from "@/lib/constants";
import type { Candidature, CandidatureStats, StatutCandidature } from "@/lib/types";
import { cn } from "@/lib/utils";

function euros(n: number | null): string {
  if (!n) return "—";
  return new Intl.NumberFormat("fr-BE", { style: "currency", currency: "EUR",
    maximumFractionDigits: 0 }).format(n);
}

/** Une carte de candidature dans une colonne. */
function Carte({ c, onDeplacer }: {
  c: Candidature; onDeplacer: (statut: StatutCandidature) => void;
}) {
  const s = c.subside;
  // Échéance passée alors que le dossier n'est pas encore soumis : on grise et
  // on signale — sans rien automatiser, c'est à l'utilisateur de trancher.
  const j = joursAvant(s?.deadline ?? null);
  const enRetard = j !== null && j < 0 && ["a_etudier", "dossier_en_cours"].includes(c.statut);
  const obtenu = c.statut === "obtenu";

  return (
    <div className={cn(
      "rounded-[var(--radius-card)] border p-3 shadow-[var(--shadow-soft)] transition-all duration-150",
      "hover:-translate-y-px hover:border-accent/40 hover:shadow-[var(--shadow-lift)]",
      obtenu ? "border-accent/25 bg-accent-soft/40" : "border-border bg-surface",
      enRetard && "opacity-70",
    )}>
      <Link href={`/candidature/${c.id}`} className="block">
        <p className="line-clamp-2 font-display text-[15px] font-semibold leading-snug text-ink group-hover:underline">
          {s?.titre ?? "Subside"}
        </p>
        <p className="mt-1 truncate text-[12px] text-ink-soft">{s?.organisme ?? s?.source_id}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
          {enRetard ? (
            <span className="rounded-md bg-neutral-soft px-2 py-0.5 font-semibold text-neutral">échéance passée</span>
          ) : (
            <BadgeEcheance deadline={s?.deadline ?? null} permanent={s?.permanent} />
          )}
          {c.montant_demande ? (
            <span className="text-ink-faint">demandé {euros(c.montant_demande)}</span>
          ) : null}
          {obtenu && c.montant_obtenu ? (
            <span className="font-semibold text-accent">obtenu {euros(c.montant_obtenu)}</span>
          ) : null}
        </div>
      </Link>
      {enRetard && (
        <p className="mt-2 text-[11px] text-ink-faint">
          L&apos;échéance est passée — vous pouvez la passer en « abandonné » ci-dessous.
        </p>
      )}
      {/* Déplacement de statut : robuste et mobile-friendly (pas de drag). */}
      <select
        aria-label="Changer le statut"
        value={c.statut}
        onChange={(e) => onDeplacer(e.target.value as StatutCandidature)}
        className="mt-2.5 w-full rounded-[var(--radius-ctrl)] border border-border bg-surface-2 px-2 py-1.5 text-[12px] text-ink-soft"
      >
        {(["a_etudier", "dossier_en_cours", "soumis", "obtenu", "refuse", "abandonne"] as const)
          .map((st) => <option key={st} value={st}>{STATUT_LABEL[st]}</option>)}
      </select>
    </div>
  );
}

export default function CandidaturesPage() {
  useTitre("Mes candidatures");
  const router = useRouter();
  const { getToken } = useAuth();
  const toast = useToast();
  const [profilId, setProfilId] = useState<number | null>(null);
  const [liste, setListe] = useState<Candidature[] | null>(null);
  const [stats, setStats] = useState<CandidatureStats | null>(null);
  const [voirAbandonnees, setVoirAbandonnees] = useState(false);
  // Modale pour les statuts qui demandent une info (soumis / obtenu / refusé).
  const [modale, setModale] = useState<{ c: Candidature; statut: StatutCandidature } | null>(null);

  const charger = useCallback(async (pid: number) => {
    const d = await api.candidatures(pid, getToken);
    setListe(d.candidatures);
    setStats(d.stats);
  }, [getToken]);

  useEffect(() => {
    (async () => {
      const pid = await resoudreProfilId(getToken).catch(() => null);
      if (pid == null) { router.replace("/onboarding"); return; }
      setProfilId(pid);
      charger(pid).catch(() => setListe([]));
    })();
  }, [getToken, router, charger]);

  const appliquer = async (id: number, patch: Parameters<typeof api.majCandidature>[1]) => {
    await api.majCandidature(id, patch, getToken);
    // Un mot chaleureux aux moments clés — jamais de confettis plein écran.
    if (patch.statut === "obtenu") {
      const m = patch.montant_obtenu;
      toast(m ? `${euros(Number(m))} obtenus — bravo 🎉` : "Candidature acceptée — bravo 🎉", "succes");
    } else if (patch.statut === "refuse") {
      toast("Ça arrive. Le prochain appel est peut-être déjà dans vos correspondances.");
    }
    if (profilId) charger(profilId);
  };

  const deplacer = (c: Candidature, statut: StatutCandidature) => {
    // Ces trois statuts appellent une info complémentaire (optionnelle) :
    // on passe par une modale légère plutôt que d'écrire à l'aveugle.
    if (["soumis", "obtenu", "refuse"].includes(statut)) {
      setModale({ c, statut });
    } else {
      appliquer(c.id, { statut });
    }
  };

  if (liste === null) {
    return <p className="flex items-center gap-2 py-10 text-ink-soft">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Chargement…
    </p>;
  }

  const visibles = voirAbandonnees ? liste : liste.filter((c) => c.statut !== "abandonne");
  const parStatut = (st: string) => visibles.filter((c) => c.statut === st);
  const nbAbandonnees = liste.filter((c) => c.statut === "abandonne").length;

  return (
    <div>
      <header className="mb-6">
        <h1 className="font-display text-3xl font-semibold text-ink">Mes candidatures</h1>
        <p className="mt-1 text-ink-soft">
          Le suivi de vos demandes, de « à étudier » à « obtenu ». Subsidia vous
          accompagne — vous restez l&apos;auteur de chaque dossier.
        </p>
      </header>

      {stats && stats.total_candidatures > 0 && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:gap-4">
          <StatTile valeur={stats.total_candidatures} libelle="Candidatures" icon={ClipboardList} teinte="neutral" />
          <StatTile texte={euros(stats.total_demande)} libelle="Total demandé" icon={Wallet} teinte="info" />
          <StatTile texte={euros(stats.total_obtenu)} libelle="Total obtenu" accent icon={TrendingUp} teinte="accent" />
          <StatTile
            texte={stats.taux_succes == null ? "—" : `${Math.round(stats.taux_succes * 100)} %`}
            libelle="Taux de succès"
            sousTexte={stats.taux_succes == null ? `${stats.decisions}/3 décisions` : undefined}
            icon={TrendingUp} teinte="amber" />
        </div>
      )}

      {liste.length === 0 ? (
        <div className="rounded-[var(--radius-card)] border border-border bg-surface p-10 text-center">
          <IllusDossier className="mx-auto h-20 w-20" />
          <p className="mt-4 font-display text-lg text-ink">Votre première candidature</p>
          <p className="mx-auto mt-1.5 max-w-md text-ink-soft">
            Elle commence par une correspondance : depuis un subside qui vous
            correspond, cliquez sur « Préparer ma candidature ».
          </p>
          <Link href="/dashboard" className="mt-4 inline-block">
            <Button size="sm">Voir mes subsides</Button>
          </Link>
        </div>
      ) : (
        <>
          {/* Colonnes de statut : à parts égales sur la largeur (≥ 900px),
              défilement horizontal seulement sur petit écran. */}
          <div className="flex gap-4 overflow-x-auto pb-2 min-[900px]:overflow-x-visible">
            {STATUTS_CANDIDATURE.map((st) => {
              const items = parStatut(st);
              return (
                <section key={st} className="w-[260px] shrink-0 min-[900px]:w-auto min-[900px]:flex-1">
                  <div className="mb-2 flex items-center justify-between">
                    <span className={cn("rounded-full px-2.5 py-1 text-[12px] font-bold",
                      STATUT_STYLE[st])}>{STATUT_LABEL[st]}</span>
                    <span className="text-[12px] text-ink-faint">{items.length}</span>
                  </div>
                  <div className="space-y-2.5">
                    {items.map((c) => (
                      <Carte key={c.id} c={c} onDeplacer={(s) => deplacer(c, s)} />
                    ))}
                    {items.length === 0 && (
                      <p className="rounded-[var(--radius-card)] border border-dashed border-border px-3 py-4 text-center text-[12px] text-ink-faint">
                        vide
                      </p>
                    )}
                  </div>
                </section>
              );
            })}
          </div>

          {nbAbandonnees > 0 && (
            <button onClick={() => setVoirAbandonnees((v) => !v)}
              className="mt-4 text-sm font-semibold text-ink-soft hover:text-ink">
              {voirAbandonnees ? "Masquer" : "Voir"} les abandonnées ({nbAbandonnees})
            </button>
          )}
        </>
      )}

      {modale && (
        <StatutModale
          candidature={modale.c}
          statut={modale.statut}
          onFermer={() => setModale(null)}
          onValider={async (patch) => {
            await appliquer(modale.c.id, { statut: modale.statut, ...patch });
            setModale(null);
          }}
        />
      )}
    </div>
  );
}
