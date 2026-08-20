"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight, BookmarkPlus, Loader2, Pencil, RotateCw, Search, Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Textarea, CheckPill } from "@/components/ui/field";
import { CompactCard } from "@/components/compact-card";
import { FiltrePertinence, filtrerParPertinence, type FiltrePert } from "@/components/filtre-pertinence";
import { FiltreNature, filtrerParNature, type FiltreNat } from "@/components/filtre-nature";
import { IllusLoupe } from "@/components/illustrations";
import { useToast } from "@/components/toast";
import { useTitre } from "@/lib/use-titre";
import { api, ApiError } from "@/lib/api";
import { COMMUNES_19, SECTEURS } from "@/lib/constants";
import type { Matching, Recherche } from "@/lib/types";

const ELIGIBLE = ["probablement_eligible", "eligible_sous_conditions"];

const LABEL_SECTEUR: Record<string, string> =
  Object.fromEntries(SECTEURS.map((s) => [s.value, s.label]));

/** Nom pré-rempli : commune + premiers mots de la description (ou secteurs). */
function suggestionNom(commune: string, description: string, secteurs: string[]): string {
  const mots = description.trim().split(/\s+/).filter(Boolean).slice(0, 4).join(" ");
  if (mots) return `${commune} — ${mots}`;
  if (secteurs.length) return `${commune} — ${LABEL_SECTEUR[secteurs[0]] ?? secteurs[0]}`;
  return `Recherche à ${commune}`;
}

/** Petite modale de nommage, partagée entre « sauvegarder » et « renommer ». */
function ModaleNom({
  titre, valeurInitiale, cta, onValider, onFermer, occupe,
}: {
  titre: string; valeurInitiale: string; cta: string;
  onValider: (nom: string) => void; onFermer: () => void; occupe: boolean;
}) {
  const [nom, setNom] = useState(valeurInitiale);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onFermer(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onFermer]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-4"
      onClick={onFermer}>
      <div className="w-full max-w-md rounded-[var(--radius-card)] border border-border bg-surface p-5 shadow-[var(--shadow-lift)]"
        onClick={(e) => e.stopPropagation()}>
        <h2 className="font-display text-lg font-semibold text-ink">{titre}</h2>
        <div className="mt-3">
          <Label htmlFor="nom-recherche">Nom de la recherche</Label>
          <Input id="nom-recherche" value={nom} autoFocus
            onChange={(e) => setNom(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && nom.trim()) onValider(nom.trim()); }} />
        </div>
        <div className="mt-5 flex justify-end gap-2.5">
          <Button variant="ghost" size="sm" onClick={onFermer}>Annuler</Button>
          <Button size="sm" disabled={!nom.trim() || occupe}
            onClick={() => onValider(nom.trim())}>
            {occupe && <Loader2 className="h-4 w-4 animate-spin" />} {cta}
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * Recherche libre : une hypothèse ponctuelle (« et si on montait un projet
 * jeunesse à Molenbeek ? ») sans toucher au profil enregistré. On peut la
 * SAUVEGARDER (lot 8.1) : elle devient un objet à part, veillé, dans « Mes
 * recherches » — jamais mélangé au profil principal de l'ASBL.
 */
export default function RecherchePage() {
  useTitre("Recherche libre");
  const { getToken } = useAuth();
  const router = useRouter();
  const toast = useToast();

  const [commune, setCommune] = useState(COMMUNES_19[0]);
  const [secteurs, setSecteurs] = useState<string[]>([]);
  const [description, setDescription] = useState("");
  const [publics, setPublics] = useState("");

  const [etat, setEtat] = useState<"repos" | "analyse" | "fini" | "erreur">("repos");
  const [resultats, setResultats] = useState<Matching[]>([]);
  const [filtrePert, setFiltrePert] = useState<FiltrePert>("toutes");
  const [filtreNat, setFiltreNat] = useState<FiltreNat>("toutes");
  const [traites, setTraites] = useState(0);
  const [candidats, setCandidats] = useState<number | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  // Recherche courante (profil éphémère créé par le backend) + état de sauvegarde.
  const [profilCourant, setProfilCourant] = useState<number | null>(null);
  const [sauvegardee, setSauvegardee] = useState(false);
  const [occupe, setOccupe] = useState(false);

  // « Mes recherches » sauvegardées.
  const [recherches, setRecherches] = useState<Recherche[]>([]);
  const [maxRecherches, setMaxRecherches] = useState(10);
  const [modale, setModale] = useState<
    { genre: "sauver"; suggestion: string } | { genre: "renommer"; id: number; nom: string } | null>(null);
  const [confirmerSuppr, setConfirmerSuppr] = useState<number | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const vus = useRef<Set<number>>(new Set());

  const stop = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  useEffect(() => stop, []);

  const chargerRecherches = useCallback(async () => {
    try {
      const d = await api.mesRecherches(getToken);
      setRecherches(d.recherches);
      setMaxRecherches(d.max);
    } catch { /* liste indisponible : on n'empêche pas la recherche */ }
  }, [getToken]);

  useEffect(() => { (async () => { await chargerRecherches(); })(); }, [chargerRecherches]);

  const lancer = useCallback(async () => {
    stop();
    setEtat("analyse"); setResultats([]); vus.current.clear();
    setTraites(0); setCandidats(null); setErreur(null);
    setProfilCourant(null); setSauvegardee(false);
    setFiltrePert("toutes"); setFiltreNat("toutes");
    try {
      const { profil_id, job_id } = await api.rechercheLibre({
        nom: "Recherche libre",
        commune_siege: commune,
        secteurs,
        publics_cibles: publics.split(",").map((s) => s.trim()).filter(Boolean),
        description_libre: description.trim() || null,
      }, getToken);
      setProfilCourant(profil_id);

      const tick = async () => {
        let s;
        try { s = await api.statutMatching(job_id, getToken); }
        catch { stop(); setErreur("La recherche a été interrompue."); setEtat("erreur"); return; }
        setCandidats(s.total_candidats);
        setTraites(s.traites);
        const nouveaux = s.resultats.filter((m) => !vus.current.has(m.subside.id));
        if (nouveaux.length) {
          nouveaux.forEach((m) => vus.current.add(m.subside.id));
          setResultats((prev) => [...prev, ...nouveaux]);
        }
        if (s.statut !== "running") { stop(); setEtat("fini"); }
      };
      tick();
      pollRef.current = setInterval(tick, 1300);
    } catch (e) {
      setErreur(e instanceof ApiError && e.status === 429
        ? "Trop de recherches d'affilée. Laissez passer une minute."
        : "La recherche n'a pas pu démarrer.");
      setEtat("erreur");
    }
  }, [commune, secteurs, publics, description, getToken]);

  // Sauvegarde de la recherche courante (transforme l'éphémère en « recherche »).
  const sauvegarder = async (nom: string) => {
    if (profilCourant == null) return;
    setOccupe(true);
    try {
      await api.sauvegarderRecherche(profilCourant, nom, getToken);
      setSauvegardee(true);
      setModale(null);
      toast("Recherche sauvegardée — elle sera veillée pour vous.", "succes");
      chargerRecherches();
    } catch (e) {
      toast(e instanceof ApiError && e.status === 409
        ? `Limite de ${maxRecherches} recherches atteinte. Supprimez-en une d'abord.`
        : "La sauvegarde a échoué.");
    } finally { setOccupe(false); }
  };

  const renommer = async (id: number, nom: string) => {
    setOccupe(true);
    try {
      await api.renommerRecherche(id, nom, getToken);
      setModale(null);
      chargerRecherches();
    } catch { toast("Le renommage a échoué."); }
    finally { setOccupe(false); }
  };

  const relancer = async (id: number) => {
    try {
      await api.lancerMatching(id, getToken);
      toast("Analyse relancée — les résultats se mettront à jour.", "succes");
    } catch { toast("Impossible de relancer pour le moment."); }
  };

  const supprimer = async (id: number) => {
    setConfirmerSuppr(null);
    try {
      await api.supprimerProfil(id, getToken);
      toast("Recherche supprimée.");
      chargerRecherches();
    } catch { toast("La suppression a échoué."); }
  };

  const eligibles = resultats.filter((m) => ELIGIBLE.includes(m.verdict));
  const eligiblesAffiches = filtrerParNature(filtrerParPertinence(eligibles, filtrePert), filtreNat);
  const enCours = etat === "analyse";
  const peutSauver = etat === "fini" && profilCourant != null && !sauvegardee;

  return (
    <div>
      <header className="mb-6">
        <h1 className="font-display text-3xl font-semibold text-ink">Recherche libre</h1>
        <p className="mt-1 text-ink-soft">
          Testez une hypothèse — un autre quartier, un autre projet — sans toucher
          à votre profil. Sauvegardez-la pour la retrouver et la faire veiller.
        </p>
      </header>

      <div className="rounded-[var(--radius-card)] border border-border bg-surface p-5 shadow-[var(--shadow-soft)]">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="commune">Commune du projet</Label>
            <Select id="commune" value={commune} onChange={(e) => setCommune(e.target.value)}>
              {COMMUNES_19.map((c) => <option key={c}>{c}</option>)}
            </Select>
          </div>
          <div>
            <Label htmlFor="publics" optional>Publics cibles</Label>
            <Input id="publics" value={publics} onChange={(e) => setPublics(e.target.value)}
              placeholder="ex : jeunes, primo-arrivants" />
          </div>
        </div>

        <div className="mt-4">
          <Label optional>Secteurs</Label>
          <div className="flex flex-wrap gap-2">
            {SECTEURS.map((s) => (
              <CheckPill key={s.value} checked={secteurs.includes(s.value)}
                onChange={(v) => setSecteurs(v
                  ? [...secteurs, s.value]
                  : secteurs.filter((x) => x !== s.value))}>
                {s.label}
              </CheckPill>
            ))}
          </div>
        </div>

        <div className="mt-4">
          <Label htmlFor="desc" optional>Décrivez le projet</Label>
          <Textarea id="desc" value={description} onChange={(e) => setDescription(e.target.value)}
            placeholder="Un atelier vélo partagé dans un quartier populaire, ouvert le samedi, animé par des bénévoles." />
          <p className="mt-1.5 text-xs text-ink-faint">
            C&apos;est ce champ qui pèse le plus : quelques phrases précises valent mieux qu&apos;une liste.
          </p>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <Button onClick={lancer} disabled={enCours}>
            {enCours ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            {enCours ? "Analyse…" : "Lancer la recherche"}
          </Button>
          {enCours && candidats !== null && (
            <span className="text-sm text-ink-soft">{traites}/{candidats} analysés</span>
          )}
          {peutSauver && (
            <Button variant="subtle" onClick={() =>
              setModale({ genre: "sauver", suggestion: suggestionNom(commune, description, secteurs) })}>
              <BookmarkPlus className="h-4 w-4" /> Sauvegarder cette recherche
            </Button>
          )}
          {sauvegardee && (
            <span className="text-sm font-medium text-accent">✓ Recherche sauvegardée</span>
          )}
        </div>

        {erreur && <p className="mt-3 text-sm text-danger">{erreur}</p>}
      </div>

      {eligibles.length > 1 && (
        <div className="mt-6 flex flex-wrap items-center justify-end gap-x-5 gap-y-2">
          <FiltreNature eligibles={eligibles} valeur={filtreNat} onChange={setFiltreNat} />
          <FiltrePertinence eligibles={eligibles} valeur={filtrePert} onChange={setFiltrePert} />
        </div>
      )}

      <div className="mt-3 grid grid-cols-1 gap-3 min-[1100px]:grid-cols-2 min-[1500px]:grid-cols-3">
        <AnimatePresence>
          {eligiblesAffiches.map((m, i) => (
            <motion.div key={m.subside.id} layout className="h-full">
              <CompactCard m={m} index={i} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {eligibles.length > 0 && eligiblesAffiches.length === 0 && (
        <p className="rounded-[var(--radius-card)] border border-dashed border-border px-4 py-6 text-center text-sm text-ink-soft">
          Aucune correspondance de pertinence «&nbsp;{filtrePert}&nbsp;».{" "}
          <button className="font-medium text-accent hover:underline" onClick={() => setFiltrePert("toutes")}>
            Voir toutes les correspondances
          </button>
        </p>
      )}

      {etat === "repos" && eligibles.length === 0 && (
        <div className="mt-6 rounded-[var(--radius-card)] border border-border bg-surface p-10 text-center">
          <IllusLoupe className="mx-auto h-20 w-20" />
          <p className="mt-4 font-display text-lg text-ink">Testez une hypothèse</p>
          <p className="mx-auto mt-1.5 max-w-md text-ink-soft">
            Décrivez un projet ci-dessus et lancez la recherche : les subsides qui
            pourraient lui correspondre apparaîtront ici. Rien n&apos;est enregistré
            tant que vous ne sauvegardez pas.
          </p>
        </div>
      )}

      {etat === "fini" && eligibles.length === 0 && (
        <p className="mt-6 rounded-[var(--radius-card)] border border-border bg-surface p-6 text-center text-ink-soft">
          Aucune correspondance forte pour cette hypothèse. Essayez une description
          plus détaillée, ou d&apos;autres secteurs.
        </p>
      )}

      {/* ------------------------------- Mes recherches ------------------------------- */}
      <section className="mt-10 border-t border-border pt-8">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="font-display text-lg font-semibold text-ink">Mes recherches</h2>
          <span className="text-[13px] text-ink-faint">{recherches.length}/{maxRecherches}</span>
        </div>

        {recherches.length === 0 ? (
          <p className="mt-3 text-sm text-ink-soft">
            Aucune recherche sauvegardée. Lancez une hypothèse ci-dessus, puis
            « Sauvegarder cette recherche » pour la retrouver ici et la faire veiller.
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {recherches.map((r) => (
              <li key={r.id}
                className="rounded-[var(--radius-card)] border border-border bg-surface p-4 shadow-[var(--shadow-soft)]">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-display text-[15px] font-semibold text-ink">{r.nom_recherche}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-ink-soft">
                      <span>{r.commune_siege}</span>
                      {r.secteurs.slice(0, 3).map((s) => (
                        <span key={s} className="rounded-md bg-surface-2 px-1.5 py-0.5">
                          {LABEL_SECTEUR[s] ?? s}
                        </span>
                      ))}
                      <span className="text-ink-faint">
                        · {r.correspondances} correspondance{r.correspondances > 1 ? "s" : ""}
                      </span>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Button size="sm" onClick={() => router.push(`/dashboard?profil=${r.id}`)}>
                      Ouvrir <ArrowRight className="h-4 w-4" />
                    </Button>
                    <button title="Relancer l'analyse" aria-label="Relancer l'analyse"
                      onClick={() => relancer(r.id)}
                      className="rounded-[var(--radius-ctrl)] border border-border p-2 text-ink-soft hover:bg-surface-2 hover:text-ink">
                      <RotateCw className="h-4 w-4" />
                    </button>
                    <button title="Renommer" aria-label="Renommer"
                      onClick={() => setModale({ genre: "renommer", id: r.id, nom: r.nom_recherche })}
                      className="rounded-[var(--radius-ctrl)] border border-border p-2 text-ink-soft hover:bg-surface-2 hover:text-ink">
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button title="Supprimer" aria-label="Supprimer"
                      onClick={() => setConfirmerSuppr(r.id)}
                      className="rounded-[var(--radius-ctrl)] border border-border p-2 text-ink-soft hover:bg-surface-2 hover:text-danger">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                {confirmerSuppr === r.id && (
                  <div className="mt-3 flex flex-wrap items-center gap-3 rounded-[var(--radius-ctrl)] bg-surface-2 px-3 py-2 text-sm">
                    <span className="text-ink">Supprimer cette recherche et ses analyses ?</span>
                    <div className="flex gap-2">
                      <Button size="sm" variant="ghost" onClick={() => setConfirmerSuppr(null)}>Annuler</Button>
                      <button onClick={() => supprimer(r.id)}
                        className="rounded-[var(--radius-ctrl)] bg-danger px-3 py-1.5 text-sm font-medium text-white hover:opacity-90">
                        Supprimer
                      </button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {modale && (
        <ModaleNom
          titre={modale.genre === "sauver" ? "Sauvegarder cette recherche" : "Renommer la recherche"}
          valeurInitiale={modale.genre === "sauver" ? modale.suggestion : modale.nom}
          cta={modale.genre === "sauver" ? "Sauvegarder" : "Renommer"}
          occupe={occupe}
          onFermer={() => setModale(null)}
          onValider={(nom) => modale.genre === "sauver" ? sauvegarder(nom) : renommer(modale.id, nom)}
        />
      )}
    </div>
  );
}
