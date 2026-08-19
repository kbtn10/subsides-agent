"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { AnimatePresence, motion } from "framer-motion";
import { CalendarClock, Clock, Loader2, Radar, RotateCw, Sparkles, UserCog } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CompactCard } from "@/components/compact-card";
import { RappelsCandidatures } from "@/components/rappels-candidatures";
import { IllusRadar } from "@/components/illustrations";
import { StatTile } from "@/components/stat-tile";
import { AnimatedNumber } from "@/components/animated-number";
import { api, ApiError } from "@/lib/api";
import { oublierProfilCache, resoudreProfilId } from "@/lib/profil-courant";
import { useTitre } from "@/lib/use-titre";
import type { Matching, Resume } from "@/lib/types";

type Phase = "chargement" | "analyse" | "termine" | "vide" | "erreur";
const ELIGIBLE = ["probablement_eligible", "eligible_sous_conditions"];

/** Fraîcheur lisible : « il y a 3 h », « il y a 2 j ». */
export function fraicheur(iso: string | null): string {
  if (!iso) return "jamais";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "inconnue";
  const h = Math.floor(ms / 3_600_000);
  if (h < 1) return "à l'instant";
  if (h < 24) return `il y a ${h} h`;
  return `il y a ${Math.floor(h / 24)} j`;
}

export default function DashboardPage() {
  useTitre("Mes subsides");
  const router = useRouter();
  const { getToken } = useAuth();

  const [phase, setPhase] = useState<Phase>("chargement");
  const [totalBase, setTotalBase] = useState(0);
  const [maj, setMaj] = useState<string | null>(null);
  const [candidats, setCandidats] = useState<number | null>(null);
  const [traites, setTraites] = useState(0);
  const [resultats, setResultats] = useState<Matching[]>([]);
  const [resume, setResume] = useState<Resume | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [nonReplie, setNonReplie] = useState(false);
  const [nom, setNom] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const vus = useRef<Set<number>>(new Set());
  const profilId = useRef<number | null>(null);
  const [pidRappels, setPidRappels] = useState<number | null>(null);

  const stopPoll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  // UN seul appel pour tout le dashboard : résumé + correspondances + fraîcheur.
  const charger = useCallback(async (pid: number) => {
    const d = await api.dashboard(pid, getToken);
    setNom(d.profil?.nom ?? null);
    setTotalBase(d.total_subsides);
    setMaj(d.derniere_maj);
    setResume(d.resume);
    d.matchings.forEach((m) => vus.current.add(m.subside.id));
    setResultats(d.matchings);
    return d;
  }, [getToken]);

  const suivre = useCallback((pid: number, jobId: string) => {
    stopPoll();
    const tick = async () => {
      let s;
      try { s = await api.statutMatching(jobId, getToken); }
      catch {
        stopPoll();
        setErreur("L'analyse a été interrompue.");
        setPhase("erreur");
        return;
      }
      setCandidats(s.total_candidats);
      setTraites(s.traites);
      // Streaming : on n'ajoute que les nouveaux → stagger conservé sur les cartes compactes.
      const nouveaux = s.resultats.filter((m) => !vus.current.has(m.subside.id));
      if (nouveaux.length) {
        nouveaux.forEach((m) => vus.current.add(m.subside.id));
        setResultats((prev) => [...prev, ...nouveaux]);
      }
      if (s.statut !== "running") {
        stopPoll();
        const d = await charger(pid).catch(() => null);
        const forts = (d?.matchings ?? s.resultats).filter((m) => ELIGIBLE.includes(m.verdict));
        setPhase(forts.length ? "termine" : "vide");
      }
    };
    tick();
    pollRef.current = setInterval(tick, 1300);
  }, [getToken, charger]);

  const lancer = useCallback(async (pid: number) => {
    setPhase("analyse"); setResultats([]); vus.current.clear();
    setTraites(0); setCandidats(null); setErreur(null);
    try {
      const { job_id } = await api.lancerMatching(pid, getToken);
      suivre(pid, job_id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // Une analyse tourne déjà ailleurs : on affiche l'existant.
        const d = await charger(pid).catch(() => null);
        const forts = (d?.matchings ?? []).filter((m) => ELIGIBLE.includes(m.verdict));
        setPhase(forts.length ? "termine" : "vide");
      } else {
        setErreur("L'analyse n'a pas pu démarrer.");
        setPhase("erreur");
      }
    }
  }, [getToken, suivre, charger]);

  useEffect(() => {
    (async () => {
      // Résout le profil via le cache OU l'API (résilient au localStorage vide).
      let pid: number | null;
      try {
        pid = await resoudreProfilId(getToken);
      } catch {
        pid = null;   // API injoignable : on retentera au prochain rendu
      }
      if (pid == null) { router.replace("/onboarding"); return; }
      profilId.current = pid;
      setPidRappels(pid);
      try {
        const d = await charger(pid);
        if (d.matchings.length) {
          const forts = d.matchings.filter((m) => ELIGIBLE.includes(m.verdict));
          setPhase(forts.length ? "termine" : "vide");
        } else {
          lancer(pid);
        }
      } catch (e) {
        // Profil disparu ou appartenant à quelqu'un d'autre : on repart de l'onboarding.
        if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
          oublierProfilCache();
          router.replace("/onboarding");
          return;
        }
        lancer(pid);
      }
    })();
    return stopPoll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const eligibles = resultats.filter((m) => ELIGIBLE.includes(m.verdict));
  const nonRetenus = resultats.filter((m) => m.verdict === "non_eligible");
  const erreurs = resultats.filter((m) => m.verdict === "erreur");
  // Tout en erreur et rien d'éligible : ne pas faire passer ça pour « aucune correspondance ».
  const analyseRatee = eligibles.length === 0 && nonRetenus.length === 0 && erreurs.length > 0;
  const relancer = () => { if (profilId.current) lancer(profilId.current); };

  const nbCorr = resume?.correspondances ?? eligibles.length;
  const nbEch = resume?.deadlines_60j ?? 0;
  const sousLigne = nbCorr > 0
    ? `${nbCorr} correspondance${nbCorr > 1 ? "s" : ""} vous ${nbCorr > 1 ? "attendent" : "attend"}`
      + (nbEch > 0 ? ` · ${nbEch} échéance${nbEch > 1 ? "s" : ""} approche${nbEch > 1 ? "nt" : ""}` : "")
    : "Tout est calme — votre veille tourne.";

  return (
    <div>
      <header className="mb-6">
        <h1 className="font-display text-3xl font-semibold text-ink">
          Bonjour{nom ? `, ${nom}` : ""}
        </h1>
        <p className="mt-1 text-ink-soft">{sousLigne}</p>
      </header>

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
        <StatTile valeur={nbCorr} libelle="Correspondances" accent icon={Sparkles} teinte="accent" />
        <StatTile valeur={nbEch} libelle="Échéances < 60 jours" icon={CalendarClock} teinte="amber" />
        <StatTile valeur={totalBase} libelle="Subsides surveillés" icon={Radar} teinte="accent" />
        <StatTile texte={fraicheur(maj)} libelle="Données à jour" icon={Clock} teinte="info" />
      </div>

      {pidRappels && <RappelsCandidatures profilId={pidRappels} />}

      {phase === "chargement" && (
        <p className="flex items-center gap-2 text-ink-soft">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Chargement…
        </p>
      )}

      {phase === "analyse" && (
        <motion.div layout
          className="mb-5 rounded-[var(--radius-card)] border border-info/25 bg-info-soft p-4">
          <p className="text-[15px] text-ink">
            <span className="font-semibold"><AnimatedNumber value={totalBase} /></span> subsides suivis
            {candidats !== null && <>
              {" → "}<span className="font-semibold"><AnimatedNumber value={candidats} /></span>{" "}
              correspondent à votre zone
            </>}
            {" → "}<span className="text-ink-soft">analyse en cours…</span>
          </p>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/70">
            <motion.div className="h-full bg-accent"
              animate={{ width: candidats ? `${Math.round((traites / candidats) * 100)}%` : "12%" }}
              transition={{ duration: 0.5, ease: "easeOut" }} />
          </div>
          <p className="mt-2 flex items-center gap-1.5 text-sm text-ink-soft">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            <span>
              <AnimatedNumber value={traites} />{candidats ? `/${candidats}` : ""} analysés
              {" · "}<AnimatedNumber value={eligibles.length} /> correspondance{eligibles.length > 1 ? "s" : ""}
            </span>
          </p>
        </motion.div>
      )}

      {(phase === "erreur" || analyseRatee) && (
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border border-border bg-surface-2 p-4">
          <p className="text-ink">
            {erreur ?? "L'analyse n'a pas pu aboutir pour le moment."} Réessayez dans un instant.
          </p>
          <Button size="sm" variant="ghost" onClick={relancer}>
            <RotateCw className="h-4 w-4" /> Réessayer
          </Button>
        </div>
      )}

      {(phase === "termine" || phase === "vide") && !analyseRatee && (
        <div className="mb-5 flex items-center gap-2.5 rounded-[var(--radius-card)] bg-accent-soft px-4 py-3 text-sm text-accent">
          <span className="veille-dot inline-block h-2 w-2 shrink-0 rounded-full bg-accent" aria-hidden />
          <span>Votre veille est active — les nouveaux appels correspondant à votre profil apparaîtront ici.</span>
        </div>
      )}

      {eligibles.length > 0 && (
        <h2 className="mb-3 font-display text-lg font-semibold text-ink">Vos subsides</h2>
      )}

      <div className="space-y-3">
        <AnimatePresence>
          {eligibles.map((m, i) => (
            <motion.div key={m.subside.id} layout>
              <CompactCard m={m} index={i} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {phase === "vide" && eligibles.length === 0 && !analyseRatee && (
        <div className="rounded-[var(--radius-card)] border border-border bg-surface p-10 text-center">
          <IllusRadar className="mx-auto h-20 w-20" />
          <p className="mt-4 font-display text-lg text-ink">Rien de fortement adéquat aujourd&apos;hui</p>
          <p className="mx-auto mt-1.5 max-w-md text-ink-soft">
            Votre veille tourne : dès qu&apos;un appel vous correspond, il apparaît ici.
            Vous pouvez aussi enrichir votre profil pour affiner l&apos;analyse.
          </p>
          <Link href="/onboarding?edit=1" className="mt-4 inline-block">
            <Button variant="ghost" size="sm"><UserCog className="h-4 w-4" /> Enrichir mon profil</Button>
          </Link>
        </div>
      )}

      {!analyseRatee && erreurs.length > 0 && (
        <p className="mt-4 text-sm text-ink-faint">
          {erreurs.length} subside{erreurs.length > 1 ? "s n'ont" : " n'a"} pas pu être analysé
          {erreurs.length > 1 ? "s" : ""} cette fois.{" "}
          <button className="font-medium text-accent hover:underline" onClick={relancer}>Réessayer</button>
        </p>
      )}

      {nonRetenus.length > 0 && (
        <section className="mt-8">
          <button onClick={() => setNonReplie((v) => !v)} aria-expanded={nonReplie}
            className="text-sm font-semibold text-ink-soft hover:text-ink">
            {nonReplie ? "Masquer" : "Voir"} les non retenus ({nonRetenus.length})
          </button>
          {nonReplie && (
            // Fond grisé-chaud : cette section recule visuellement (c'est du tri,
            // pas la matière principale).
            <div className="mt-3 rounded-[var(--radius-card)] bg-surface-2 p-4">
              <p className="text-sm text-ink-faint">
                Ces subsides existent mais un critère d&apos;éligibilité vous en écarte.
                Ce n&apos;est pas un échec, juste du tri.
              </p>
              <div className="mt-3 space-y-3">
                {nonRetenus.map((m, i) => <CompactCard key={m.subside.id} m={m} index={i} />)}
              </div>
            </div>
          )}
        </section>
      )}

      <div className="mt-10 flex flex-wrap gap-3 border-t border-border pt-6">
        <Button variant="ghost" onClick={relancer}>
          <RotateCw className="h-4 w-4" /> Relancer l&apos;analyse
        </Button>
        <Link href="/onboarding?edit=1">
          <Button variant="ghost"><UserCog className="h-4 w-4" /> Modifier mon profil</Button>
        </Link>
      </div>
    </div>
  );
}
