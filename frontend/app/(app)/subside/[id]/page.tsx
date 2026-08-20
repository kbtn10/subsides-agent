"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { motion, useReducedMotion } from "framer-motion";
import {
  AlertTriangle, ArrowLeft, ArrowUpRight, Bookmark, Check, ClipboardList, FileText,
  History, Loader2, Minus,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { BadgeEcheance, pastille } from "@/components/compact-card";
import { NatureBadge } from "@/components/nature-badge";
import { NATURE_ICON, NATURE_SANS_APPEL } from "@/lib/nature";
import { api, ApiError } from "@/lib/api";
import { VERDICT_LABEL } from "@/lib/constants";
import type { MatchingDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useTitre } from "@/lib/use-titre";

/** Bloc « une liste de critères » — même grammaire visuelle pour les 3 natures. */
function Criteres({
  titre, items, icone, couleur,
}: { titre: string; items: string[]; icone: React.ReactNode; couleur: string }) {
  if (!items.length) return null;
  return (
    <section className="mt-6">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">{titre}</h2>
      <ul className="mt-2 space-y-2">
        {items.map((c, i) => (
          <li key={i} className={cn("flex gap-2.5 text-[15px] leading-relaxed", couleur)}>
            <span className="mt-0.5 shrink-0" aria-hidden>{icone}</span>
            <span>{c}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Meta({ libelle, valeur }: { libelle: string; valeur: string | null }) {
  if (!valeur) return null;
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-ink-faint">{libelle}</dt>
      <dd className="mt-0.5 text-[15px] text-ink">{valeur}</dd>
    </div>
  );
}

export default function SubsideDetailPage() {
  useTitre("Détail du subside");
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { getToken } = useAuth();
  const reduce = useReducedMotion();

  const [m, setM] = useState<MatchingDetail | null>(null);
  const [charge, setCharge] = useState<"chargement" | "ok" | "introuvable" | "erreur">("chargement");
  const [prepare, setPrepare] = useState(false);

  // Ouvre (ou retrouve) la candidature et emmène dans l'espace de suivi.
  const preparerCandidature = async () => {
    if (!m) return;
    setPrepare(true);
    try {
      const c = await api.creerCandidature(
        { profil_id: m.profil_id, subside_id: m.subside.id, matching_id: m.id }, getToken);
      router.push(`/candidature/${c.id}`);
    } catch {
      setPrepare(false);
    }
  };

  // Un id non numérique se voit au rendu : pas besoin d'un effet pour ça.
  const id = Number(params?.id);
  const idValide = Number.isInteger(id) && id > 0;
  const etat = idValide ? charge : "introuvable";

  useEffect(() => {
    if (!idValide) return;
    api.detail(id, getToken)
      .then((d) => { setM(d); setCharge("ok"); })
      // 403 = le matching appartient à quelqu'un d'autre : on ne le distingue
      // pas d'un 404, pour ne rien révéler de l'existence de la fiche.
      .catch((e) => setCharge(e instanceof ApiError && (e.status === 404 || e.status === 403)
        ? "introuvable" : "erreur"));
  }, [id, idValide, getToken]);

  if (etat === "chargement") {
    return <p className="flex items-center gap-2 py-10 text-ink-soft">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Chargement…
    </p>;
  }

  if (etat !== "ok" || !m) {
    return (
      <div className="py-16 text-center">
        <h1 className="font-display text-2xl font-semibold text-ink">
          {etat === "introuvable" ? "Ce subside est introuvable" : "Impossible d'afficher ce subside"}
        </h1>
        <p className="mx-auto mt-2 max-w-md text-ink-soft">
          {etat === "introuvable"
            ? "Le lien est peut-être périmé, ou cette analyse ne fait pas partie de votre compte."
            : "Un souci temporaire nous empêche de charger cette analyse. Réessayez dans un instant."}
        </p>
        <Link href="/dashboard" className="mt-5 inline-block">
          <Button variant="ghost"><ArrowLeft className="h-4 w-4" /> Retour à mes subsides</Button>
        </Link>
      </div>
    );
  }

  const s = m.subside;
  const natureSansAppel = !!s.nature && NATURE_SANS_APPEL.includes(s.nature);
  // Toujours un composant valide : l'encart ne s'affiche que si natureSansAppel.
  const NatureIcone = NATURE_ICON[s.nature ?? "dispositif_permanent"];
  const organisme = s.organisme ?? "l'organisme";

  return (
    <motion.article
      initial={reduce ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
    >
      <Link href="/dashboard"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-soft hover:text-ink">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Mes subsides
      </Link>

      <header className="mt-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("rounded-full px-2.5 py-1 text-[11px] font-bold", pastille[m.verdict])}>
            {VERDICT_LABEL[m.verdict] ?? m.verdict}
          </span>
          <BadgeEcheance deadline={s.deadline} permanent={s.permanent} />
          <NatureBadge nature={s.nature} />
          {m.pertinence && <span className="text-[13px] text-ink-faint">Pertinence {m.pertinence}</span>}
        </div>
        <h1 className="mt-2.5 font-display text-[28px] font-semibold leading-tight text-ink">
          {s.titre}
        </h1>
        <p className="mt-1.5 text-ink-soft">
          {s.organisme ?? s.source_id}
          {s.montant ? <span className="text-ink-faint"> · {s.montant}</span> : null}
        </p>

        {m.recurrence && (
          <p className="mt-3 flex items-center gap-2 rounded-[var(--radius-ctrl)] bg-info-soft px-3 py-2 text-sm text-info">
            <History className="h-4 w-4 shrink-0" aria-hidden />
            Cet appel semble récurrent — une édition {m.recurrence.annee} a été détectée
            les années précédentes.
          </p>
        )}

        {/* Le pont vers l'étage 3 : préparer sa candidature (jamais soumettre).
            Trois cas : depuis une recherche (masqué, lot 8.1) ; un dispositif
            sans appel formel (encart honnête + « Suivre ») ; un appel classique. */}
        {m.profil_type === "recherche" ? (
          <p title="Disponible depuis votre profil principal"
            className="mt-4 inline-flex items-center gap-2 rounded-[var(--radius-ctrl)] border border-border bg-surface-2 px-3 py-2 text-sm text-ink-soft">
            <ClipboardList className="h-4 w-4 shrink-0" aria-hidden />
            Préparer une candidature se fait depuis votre profil principal.
          </p>
        ) : natureSansAppel ? (
          <div className="mt-4 rounded-[var(--radius-card)] border border-info/25 bg-info-soft p-4">
            <p className="flex items-center gap-2 font-medium text-ink">
              <NatureIcone className="h-4 w-4 shrink-0 text-info" aria-hidden />
              {s.nature === "financement_instrument"
                ? "Prêt / garantie — ce n'est pas une subvention"
                : "Dispositif permanent"}
            </p>
            <p className="mt-1.5 text-sm text-ink-soft">
              {s.nature === "financement_instrument"
                ? `Cet instrument (prêt, garantie, avance récupérable) se sollicite en continu auprès de ${organisme}. Vérifiez votre capacité de remboursement avant de vous lancer — ce n'est pas de l'argent donné.`
                : `Pas d'appel formel ni d'échéance : la démarche se fait en continu, directement auprès de ${organisme}.`}
            </p>
            <div className="mt-3 flex flex-wrap gap-2.5">
              <a href={s.lien_officiel ?? s.url_source} target="_blank" rel="noopener noreferrer">
                <Button size="sm">Voir la fiche officielle <ArrowUpRight className="h-4 w-4" /></Button>
              </a>
              <Button size="sm" variant="ghost" onClick={preparerCandidature} disabled={prepare}>
                {prepare ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bookmark className="h-4 w-4" />}
                Suivre ce dispositif
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-4">
            <Button onClick={preparerCandidature} disabled={prepare}>
              {prepare ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardList className="h-4 w-4" />}
              Préparer ma candidature
            </Button>
          </div>
        )}
      </header>

      {/* Deux colonnes sur grand écran : l'analyse et la fiche à gauche, une
          colonne méta collante (échéance, montant, zone, liens) à droite —
          pour ne pas étirer le texte sur toute la largeur. */}
      <div className="mt-5 grid gap-6 min-[1100px]:grid-cols-[minmax(0,1fr)_320px] min-[1100px]:items-start">
        <div className="min-w-0">
          {/* Le jugement, en toutes lettres — et jamais une promesse. */}
          {m.justification && (
            <div className="rounded-[var(--radius-card)] border border-border bg-surface p-5 shadow-[var(--shadow-soft)]">
              <p className="text-[15px] leading-relaxed text-ink">{m.justification}</p>
              <p className="mt-3 border-t border-border pt-3 text-[13px] text-ink-faint">
                Cette analyse est une aide à la décision, pas une décision. Vérifiez toujours les
                conditions sur la fiche officielle avant de candidater.
              </p>
            </div>
          )}

          <Criteres titre="À vérifier avant de candidater" items={m.criteres_a_verifier}
            icone={<AlertTriangle className="h-4 w-4 text-amber" />} couleur="text-ink" />
          <Criteres titre="Ce qui joue en votre faveur" items={m.criteres_satisfaits}
            icone={<Check className="h-4 w-4 text-accent" />} couleur="text-ink" />
          <Criteres titre="Ce qui ne correspond pas" items={m.criteres_non_satisfaits}
            icone={<Minus className="h-4 w-4 text-neutral" />} couleur="text-ink-soft" />
          <Criteres titre="Pièces généralement demandées" items={m.pieces_dossier}
            icone={<FileText className="h-4 w-4 text-ink-faint" />} couleur="text-ink-soft" />

          {/* La fiche officielle, telle qu'extraite — aucune reformulation. */}
          <section className="mt-8 rounded-[var(--radius-card)] border border-border bg-surface-2 p-5">
            <h2 className="font-display text-lg font-semibold text-ink">La fiche officielle</h2>
            {s.description && (
              <p className="mt-2 whitespace-pre-line text-[15px] leading-relaxed text-ink/90">
                {s.description}
              </p>
            )}
            {s.criteres_eligibilite?.length > 0 && (
              <div className="mt-5">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
                  Critères d&apos;éligibilité annoncés
                </h3>
                <ul className="mt-2 space-y-1.5">
                  {s.criteres_eligibilite.map((c, i) => (
                    <li key={i} className="flex gap-2 text-[15px] text-ink/90">
                      <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-ink-faint" aria-hidden />
                      <span>{c}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        </div>

        {/* Colonne méta */}
        <aside className="rounded-[var(--radius-card)] border border-border bg-surface p-5 shadow-[var(--shadow-soft)] min-[1100px]:sticky min-[1100px]:top-6">
          <dl className="grid gap-4 sm:grid-cols-2 min-[1100px]:grid-cols-1">
            <Meta libelle="Échéance" valeur={s.deadline ?? (s.permanent ? "En continu" : null)} />
            <Meta libelle="Montant" valeur={s.montant} />
            <Meta libelle="Zone géographique" valeur={s.zone_geographique} />
            <Meta libelle="Public cible" valeur={s.public_cible} />
            <Meta libelle="Bénéficiaires" valeur={s.type_beneficiaire?.join(", ") || null} />
            <Meta libelle="Secteurs" valeur={s.secteurs?.join(", ") || null} />
          </dl>
          <div className="mt-5 flex flex-col gap-2.5 border-t border-border pt-5">
            <a href={s.lien_officiel ?? s.url_source} target="_blank" rel="noopener noreferrer">
              <Button className="w-full">Voir la fiche officielle <ArrowUpRight className="h-4 w-4" /></Button>
            </a>
            {s.lien_candidature && s.lien_candidature !== s.url_source && (
              <a href={s.lien_candidature} target="_blank" rel="noopener noreferrer">
                <Button variant="ghost" className="w-full">Formulaire de candidature <ArrowUpRight className="h-4 w-4" /></Button>
              </a>
            )}
          </div>
        </aside>
      </div>
    </motion.article>
  );
}
