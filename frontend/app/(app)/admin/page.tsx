"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, ExternalLink, Loader2, Play, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/field";
import { StatTile } from "@/components/stat-tile";
import { api, ApiError } from "@/lib/api";
import type { ScrapeRun, SourceSante } from "@/lib/types";
import { cn } from "@/lib/utils";

type Fiche = {
  id: number; titre: string; source_id: string; statut: string;
  zone_categorie: string; deadline: string | null; url_source: string;
  lien_officiel?: string;
};

type StatutScrape = Awaited<ReturnType<typeof api.statutScrape>>;

function dateCourte(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleDateString("fr-BE", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

const STATUTS = ["", "nouveau", "modifie", "inchange", "a_verifier", "echec_extraction"];
const ZONES = ["", "bruxelles", "fwb", "national", "flandre", "wallonie", "autre", "inconnue"];

export default function AdminPage() {
  const { getToken } = useAuth();

  const [autorise, setAutorise] = useState<boolean | null>(null);
  const [runs, setRuns] = useState<ScrapeRun[]>([]);
  const [sante, setSante] = useState<SourceSante[]>([]);
  const [fiches, setFiches] = useState<Fiche[]>([]);
  const [fStatut, setFStatut] = useState("");
  const [fSource, setFSource] = useState("");
  const [fZone, setFZone] = useState("");
  const [job, setJob] = useState<StatutScrape | null>(null);
  const [lance, setLance] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stop = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  useEffect(() => stop, []);

  const rafraichir = useCallback(async () => {
    const [r, s] = await Promise.all([api.scrapeRuns(getToken), api.sourcesSante(getToken)]);
    setRuns(r); setSante(s);
  }, [getToken]);

  useEffect(() => {
    // Le 403 du backend est notre seule source de vérité sur le rôle admin.
    Promise.resolve()
      .then(rafraichir)
      .then(() => setAutorise(true))
      .catch((e) => setAutorise(!(e instanceof ApiError && (e.status === 403 || e.status === 401))));
  }, [rafraichir]);

  // Table des fiches : rechargée à chaque changement de filtre.
  useEffect(() => {
    if (autorise !== true) return;
    const qs = new URLSearchParams();
    if (fStatut) qs.set("statut", fStatut);
    if (fSource) qs.set("source", fSource);
    if (fZone) qs.set("zone", fZone);
    qs.set("tri", "recent");
    api.subsides(`?${qs}`, getToken)
      .then((rows) => setFiches(rows as unknown as Fiche[]))
      .catch(() => setFiches([]));
  }, [autorise, fStatut, fSource, fZone, getToken]);

  const lancerScrape = async () => {
    setErreur(null); setLance(true);
    try {
      const { job_id } = await api.lancerScrape(getToken);
      stop();
      const tick = async () => {
        try {
          const s = await api.statutScrape(job_id, getToken);
          setJob(s);
          if (s.statut !== "running") { stop(); setLance(false); rafraichir().catch(() => {}); }
        } catch { stop(); setLance(false); setErreur("Suivi du scrape interrompu."); }
      };
      tick();
      pollRef.current = setInterval(tick, 2000);
    } catch (e) {
      setLance(false);
      setErreur(e instanceof ApiError && e.status === 409
        ? "Un scrape est déjà en cours."
        : "Le scrape n'a pas pu démarrer.");
    }
  };

  if (autorise === null) {
    return <p className="flex items-center gap-2 py-10 text-ink-soft">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Chargement…
    </p>;
  }

  if (autorise === false) {
    return (
      <div className="py-16 text-center">
        <ShieldAlert className="mx-auto h-7 w-7 text-ink-faint" aria-hidden />
        <h1 className="mt-3 font-display text-2xl font-semibold text-ink">Espace réservé</h1>
        <p className="mx-auto mt-2 max-w-md text-ink-soft">
          Cette page est réservée à l&apos;administration de la plateforme.
        </p>
      </div>
    );
  }

  const dernier = runs[0];
  const echecsTotal = sante.reduce((n, s) => n + s.echecs, 0);
  const fichesTotal = sante.reduce((n, s) => n + s.fiches, 0);

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-semibold text-ink">Administration</h1>
          <p className="mt-1 text-ink-soft">Collecte, santé des sources et contenu de la base.</p>
        </div>
        <Button onClick={lancerScrape} disabled={lance}>
          {lance ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {lance ? "Collecte en cours…" : "Lancer une collecte"}
        </Button>
      </header>

      {erreur && (
        <p className="mb-4 rounded-[var(--radius-ctrl)] border border-border bg-surface-2 px-4 py-2.5 text-sm text-ink">
          {erreur}
        </p>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
        <StatTile valeur={fichesTotal} libelle="Fiches en base" />
        <StatTile valeur={sante.length} libelle="Sources configurées" />
        <StatTile valeur={echecsTotal} libelle="Fiches en échec" />
        <StatTile texte={dateCourte(dernier?.debut ?? null)} libelle="Dernière collecte" />
      </div>

      {/* Progression live */}
      {job && (
        <motion.section layout
          className="mb-6 rounded-[var(--radius-card)] border border-[#d5e2ec] bg-[#eef4f8] p-4">
          <p className="text-[15px] text-ink">
            {job.statut === "running" ? "Collecte en cours" : "Collecte terminée"}
            {job.source_en_cours && <span className="text-ink-soft"> · {job.source_en_cours}</span>}
          </p>
          <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-white/70">
            <motion.div className="h-full bg-accent"
              animate={{ width: job.fiches_total_estime
                ? `${Math.min(100, Math.round((job.fiches_traitees / job.fiches_total_estime) * 100))}%`
                : "10%" }}
              transition={{ duration: 0.5 }} />
          </div>
          <p className="mt-2 text-sm text-ink-soft">
            {job.fiches_traitees}
            {job.fiches_total_estime ? `/${job.fiches_total_estime}` : ""} fiches traitées
            {job.rapport && <>
              {" · "}{job.rapport.total_nouveaux ?? 0} nouvelles
              {" · "}{job.rapport.total_modifies ?? 0} modifiées
              {" · "}{job.rapport.total_echecs ?? 0} échecs
              {job.rapport.cout_estime_usd !== undefined && <> · ${job.rapport.cout_estime_usd?.toFixed(3)}</>}
            </>}
          </p>
          {job.erreurs.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-[13px] text-ink-soft">
              {job.erreurs.slice(0, 5).map((e, i) => <li key={i}>· {e}</li>)}
            </ul>
          )}
        </motion.section>
      )}

      {/* Santé des sources */}
      <section className="mb-8">
        <h2 className="mb-3 font-display text-xl font-semibold text-ink">Santé des sources</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {sante.map((s) => {
            const ko = s.echecs > 0 || s.erreurs_dernier_run.length > 0;
            return (
              <div key={s.id} className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-ink">{s.nom}</p>
                    <p className="text-[13px] text-ink-faint">
                      {s.id} · {s.strategie_utilisee ?? s.strategie}
                    </p>
                  </div>
                  {ko
                    ? <AlertTriangle className="h-4 w-4 shrink-0 text-amber" aria-hidden />
                    : <CheckCircle2 className="h-4 w-4 shrink-0 text-accent" aria-hidden />}
                </div>
                <p className="mt-2 text-sm text-ink-soft">
                  {s.fiches} fiche{s.fiches > 1 ? "s" : ""}
                  {s.echecs > 0 && <span className="text-amber"> · {s.echecs} en échec</span>}
                  {" · "}dernier passage {dateCourte(s.dernier_passage)}
                </p>
                {s.erreurs_dernier_run.length > 0 && (
                  <ul className="mt-1.5 space-y-0.5 text-[13px] text-ink-faint">
                    {s.erreurs_dernier_run.slice(0, 3).map((e, i) => <li key={i}>· {e}</li>)}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* Historique */}
      <section className="mb-8">
        <h2 className="mb-3 font-display text-xl font-semibold text-ink">Historique des collectes</h2>
        <div className="overflow-x-auto rounded-[var(--radius-card)] border border-border bg-surface">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="border-b border-border text-left text-xs uppercase tracking-wide text-ink-faint">
              <tr>
                <th className="px-4 py-2.5 font-semibold">Début</th>
                <th className="px-4 py-2.5 font-semibold">Durée</th>
                <th className="px-4 py-2.5 font-semibold">Nouvelles</th>
                <th className="px-4 py-2.5 font-semibold">Modifiées</th>
                <th className="px-4 py-2.5 font-semibold">Inchangées</th>
                <th className="px-4 py-2.5 font-semibold">Échecs</th>
                <th className="px-4 py-2.5 font-semibold">Coût</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-2.5 text-ink">{dateCourte(r.debut)}</td>
                  <td className="px-4 py-2.5 text-ink-soft">
                    {r.resume.duree_secondes != null ? `${Math.round(r.resume.duree_secondes)} s` : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-ink">{r.resume.nouveaux ?? 0}</td>
                  <td className="px-4 py-2.5 text-ink">{r.resume.modifies ?? 0}</td>
                  <td className="px-4 py-2.5 text-ink-soft">{r.resume.inchanges ?? 0}</td>
                  <td className={cn("px-4 py-2.5", r.resume.echecs ? "text-amber" : "text-ink-soft")}>
                    {r.resume.echecs ?? 0}
                  </td>
                  <td className="px-4 py-2.5 text-ink-soft">
                    {r.resume.cout_estime_usd != null ? `$${r.resume.cout_estime_usd.toFixed(3)}` : "—"}
                  </td>
                </tr>
              ))}
              {runs.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-6 text-center text-ink-faint">
                  Aucune collecte enregistrée.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Contenu de la base */}
      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <h2 className="font-display text-xl font-semibold text-ink">
            Fiches en base <span className="text-ink-faint">({fiches.length})</span>
          </h2>
          <div className="flex flex-wrap gap-2">
            <Select aria-label="Statut" value={fStatut} onChange={(e) => setFStatut(e.target.value)}
              className="w-auto">
              {STATUTS.map((s) => <option key={s} value={s}>{s || "Tous les statuts"}</option>)}
            </Select>
            <Select aria-label="Source" value={fSource} onChange={(e) => setFSource(e.target.value)}
              className="w-auto">
              <option value="">Toutes les sources</option>
              {sante.map((s) => <option key={s.id} value={s.id}>{s.nom}</option>)}
            </Select>
            <Select aria-label="Zone" value={fZone} onChange={(e) => setFZone(e.target.value)}
              className="w-auto">
              {ZONES.map((z) => <option key={z} value={z}>{z || "Toutes les zones"}</option>)}
            </Select>
          </div>
        </div>

        <div className="overflow-x-auto rounded-[var(--radius-card)] border border-border bg-surface">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-border text-left text-xs uppercase tracking-wide text-ink-faint">
              <tr>
                <th className="px-4 py-2.5 font-semibold">Titre</th>
                <th className="px-4 py-2.5 font-semibold">Source</th>
                <th className="px-4 py-2.5 font-semibold">Statut</th>
                <th className="px-4 py-2.5 font-semibold">Zone</th>
                <th className="px-4 py-2.5 font-semibold">Échéance</th>
                <th className="px-4 py-2.5 font-semibold sr-only">Lien</th>
              </tr>
            </thead>
            <tbody>
              {fiches.map((f) => (
                <tr key={f.id} className="border-b border-border last:border-0">
                  <td className="max-w-[320px] truncate px-4 py-2.5 text-ink" title={f.titre}>{f.titre}</td>
                  <td className="px-4 py-2.5 text-ink-soft">{f.source_id}</td>
                  <td className={cn("px-4 py-2.5",
                    f.statut === "echec_extraction" ? "text-amber" : "text-ink-soft")}>
                    {f.statut}
                  </td>
                  <td className="px-4 py-2.5 text-ink-soft">{f.zone_categorie}</td>
                  <td className="px-4 py-2.5 text-ink-soft">{f.deadline ?? "—"}</td>
                  <td className="px-4 py-2.5">
                    <a href={f.lien_officiel ?? f.url_source} target="_blank" rel="noopener noreferrer"
                      className="text-accent hover:underline" aria-label={`Ouvrir ${f.titre}`}>
                      <ExternalLink className="h-4 w-4" aria-hidden />
                    </a>
                  </td>
                </tr>
              ))}
              {fiches.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-ink-faint">
                  Aucune fiche pour ces filtres.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
