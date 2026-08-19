"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { motion, useReducedMotion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { joursAvant, pastille } from "@/components/compact-card";
import { IllusCalendrier } from "@/components/illustrations";
import { useTitre } from "@/lib/use-titre";
import { api } from "@/lib/api";
import { resoudreProfilId } from "@/lib/profil-courant";
import { RappelsCandidatures } from "@/components/rappels-candidatures";
import { VERDICT_LABEL } from "@/lib/constants";
import type { Matching } from "@/lib/types";
import { cn } from "@/lib/utils";

const ELIGIBLE = ["probablement_eligible", "eligible_sous_conditions"];

const MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
  "août", "septembre", "octobre", "novembre", "décembre"];

function cleMois(d: Date) { return `${d.getFullYear()}-${String(d.getMonth()).padStart(2, "0")}`; }
function libelleMois(d: Date) { return `${MOIS[d.getMonth()]} ${d.getFullYear()}`; }

/** Urgence : < 7 j = rouge sobre, < 30 j = ambre, sinon neutre. */
function ton(j: number) {
  if (j < 7) return { point: "bg-danger", texte: "text-danger", fond: "border-danger/30" };
  if (j < 30) return { point: "bg-amber", texte: "text-amber", fond: "border-amber/30" };
  return { point: "bg-neutral", texte: "text-ink-soft", fond: "border-border" };
}

export default function EcheancesPage() {
  useTitre("Échéances");
  const router = useRouter();
  const { getToken } = useAuth();
  const reduce = useReducedMotion();
  const [items, setItems] = useState<Matching[] | null>(null);
  const [erreur, setErreur] = useState(false);
  const [pid, setPid] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      // Résout le profil via le cache OU l'API (résilient au localStorage vide).
      let pid: number | null;
      try {
        pid = await resoudreProfilId(getToken);
      } catch {
        setErreur(true);
        return;
      }
      if (pid == null) { router.replace("/onboarding"); return; }
      setPid(pid);
      try {
        const d = await api.dashboard(pid, getToken);
        // Uniquement ce qui vous concerne, daté, et pas encore passé.
        const avecDate = d.matchings
          .filter((m) => ELIGIBLE.includes(m.verdict) && m.subside.deadline)
          .filter((m) => (joursAvant(m.subside.deadline) ?? -1) >= 0)
          .sort((a, b) => (a.subside.deadline! < b.subside.deadline! ? -1 : 1));
        setItems(avecDate);
      } catch {
        setErreur(true);
      }
    })();
  }, [router, getToken]);

  if (erreur) {
    return (
      <div className="py-16 text-center">
        <h1 className="font-display text-2xl font-semibold text-ink">Échéances indisponibles</h1>
        <p className="mt-2 text-ink-soft">Réessayez dans un instant.</p>
      </div>
    );
  }

  if (!items) {
    return <p className="flex items-center gap-2 py-10 text-ink-soft">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Chargement…
    </p>;
  }

  // Regroupement par mois, dans l'ordre chronologique.
  const groupes: { cle: string; libelle: string; lignes: Matching[] }[] = [];
  for (const m of items) {
    const d = new Date(m.subside.deadline!);
    const cle = cleMois(d);
    const dernier = groupes[groupes.length - 1];
    if (dernier && dernier.cle === cle) dernier.lignes.push(m);
    else groupes.push({ cle, libelle: libelleMois(d), lignes: [m] });
  }

  const urgents = items.filter((m) => (joursAvant(m.subside.deadline) ?? 999) < 30).length;

  return (
    <div className="mx-auto max-w-[900px]">
      {pid && <RappelsCandidatures profilId={pid} />}

      <header className="mb-6">
        <h1 className="font-display text-3xl font-semibold text-ink">Échéances</h1>
        <p className="mt-1 text-ink-soft">
          {items.length === 0
            ? "Aucune échéance datée parmi vos correspondances."
            : <>{items.length} échéance{items.length > 1 ? "s" : ""} à venir
                {urgents > 0 && <> · <span className="font-semibold text-amber">{urgents} dans les 30 jours</span></>}.</>}
        </p>
      </header>

      {items.length === 0 && (
        <div className="rounded-[var(--radius-card)] border border-border bg-surface p-10 text-center">
          <IllusCalendrier className="mx-auto h-20 w-20" />
          <p className="mt-4 font-display text-lg text-ink">Aucune échéance pressante</p>
          <p className="mx-auto mt-1.5 max-w-md text-ink-soft">
            Profitez-en pour explorer vos correspondances — dès qu&apos;un appel daté
            vous correspond, il apparaît ici.
          </p>
          <Link href="/dashboard" className="mt-4 inline-block">
            <Button size="sm">Explorer mes correspondances</Button>
          </Link>
        </div>
      )}

      <div className="space-y-8">
        {groupes.map((g, gi) => (
          <section key={g.cle}>
            <h2 className="mb-3 font-display text-lg font-semibold capitalize text-ink">{g.libelle}</h2>
            {/* Timeline : un filet vertical, un point par échéance. */}
            <ol className="relative border-l border-border pl-5">
              {g.lignes.map((m, i) => {
                const j = joursAvant(m.subside.deadline)!;
                const t = ton(j);
                return (
                  <motion.li
                    key={m.id}
                    initial={reduce ? false : { opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.3, delay: reduce ? 0 : Math.min((gi * 3 + i) * 0.05, 0.6) }}
                    className="relative mb-3 last:mb-0"
                  >
                    <span className={cn("absolute -left-[26px] top-4 h-2 w-2 rounded-full ring-4 ring-bg", t.point)}
                      aria-hidden />
                    <Link href={`/subside/${m.id}`}
                      className={cn(
                        "block rounded-[var(--radius-card)] border bg-surface px-4 py-3 transition-all duration-150",
                        "hover:-translate-y-px hover:bg-surface-2 hover:shadow-[var(--shadow-lift)]",
                        t.fond,
                      )}>
                      <div className="flex items-start justify-between gap-3">
                        <p className="truncate font-medium text-ink">{m.subside.titre}</p>
                        <span className={cn("shrink-0 text-sm font-semibold", t.texte)}>
                          {j === 0 ? "Aujourd'hui" : `J-${j}`}
                        </span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-ink-soft">
                        <span className="truncate">{m.subside.organisme ?? m.subside.source_id}</span>
                        <span className="text-ink-faint">·</span>
                        <span>{m.subside.deadline}</span>
                        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-bold", pastille[m.verdict])}>
                          {VERDICT_LABEL[m.verdict] ?? m.verdict}
                        </span>
                      </div>
                    </Link>
                  </motion.li>
                );
              })}
            </ol>
          </section>
        ))}
      </div>
    </div>
  );
}
