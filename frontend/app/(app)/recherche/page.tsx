"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { AnimatePresence, motion } from "framer-motion";
import { Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Textarea, CheckPill } from "@/components/ui/field";
import { CompactCard } from "@/components/compact-card";
import { IllusLoupe } from "@/components/illustrations";
import { useTitre } from "@/lib/use-titre";
import { api, ApiError } from "@/lib/api";
import { COMMUNES_19, SECTEURS } from "@/lib/constants";
import type { Matching } from "@/lib/types";

const ELIGIBLE = ["probablement_eligible", "eligible_sous_conditions"];

/**
 * Recherche libre : une hypothèse ponctuelle (« et si on montait un projet
 * jeunesse à Molenbeek ? ») sans toucher au profil enregistré. Le backend crée
 * un profil éphémère, on n'écrit rien dans le profil de l'utilisateur.
 */
export default function RecherchePage() {
  useTitre("Recherche libre");
  const { getToken } = useAuth();

  const [commune, setCommune] = useState(COMMUNES_19[0]);
  const [secteurs, setSecteurs] = useState<string[]>([]);
  const [description, setDescription] = useState("");
  const [publics, setPublics] = useState("");

  const [etat, setEtat] = useState<"repos" | "analyse" | "fini" | "erreur">("repos");
  const [resultats, setResultats] = useState<Matching[]>([]);
  const [traites, setTraites] = useState(0);
  const [candidats, setCandidats] = useState<number | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const vus = useRef<Set<number>>(new Set());

  const stop = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  useEffect(() => stop, []);

  const lancer = useCallback(async () => {
    stop();
    setEtat("analyse"); setResultats([]); vus.current.clear();
    setTraites(0); setCandidats(null); setErreur(null);
    try {
      const { job_id } = await api.rechercheLibre({
        nom: "Recherche libre",
        commune_siege: commune,
        secteurs,
        publics_cibles: publics.split(",").map((s) => s.trim()).filter(Boolean),
        description_libre: description.trim() || null,
      }, getToken);

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

  const eligibles = resultats.filter((m) => ELIGIBLE.includes(m.verdict));
  const enCours = etat === "analyse";

  return (
    <div>
      <header className="mb-6">
        <h1 className="font-display text-3xl font-semibold text-ink">Recherche libre</h1>
        <p className="mt-1 text-ink-soft">
          Testez une hypothèse — un autre quartier, un autre projet — sans toucher
          à votre profil. Rien n&apos;est enregistré.
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

        <div className="mt-5 flex items-center gap-3">
          <Button onClick={lancer} disabled={enCours}>
            {enCours ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            {enCours ? "Analyse…" : "Lancer la recherche"}
          </Button>
          {enCours && candidats !== null && (
            <span className="text-sm text-ink-soft">{traites}/{candidats} analysés</span>
          )}
        </div>

        {erreur && <p className="mt-3 text-sm text-danger">{erreur}</p>}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-3 min-[1100px]:grid-cols-2 min-[1500px]:grid-cols-3">
        <AnimatePresence>
          {eligibles.map((m, i) => (
            <motion.div key={m.subside.id} layout>
              <CompactCard m={m} index={i} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {etat === "repos" && eligibles.length === 0 && (
        <div className="mt-6 rounded-[var(--radius-card)] border border-border bg-surface p-10 text-center">
          <IllusLoupe className="mx-auto h-20 w-20" />
          <p className="mt-4 font-display text-lg text-ink">Testez une hypothèse</p>
          <p className="mx-auto mt-1.5 max-w-md text-ink-soft">
            Décrivez un projet ci-dessus et lancez la recherche : les subsides qui
            pourraient lui correspondre apparaîtront ici. Rien n&apos;est enregistré.
          </p>
        </div>
      )}

      {etat === "fini" && eligibles.length === 0 && (
        <p className="mt-6 rounded-[var(--radius-card)] border border-border bg-surface p-6 text-center text-ink-soft">
          Aucune correspondance forte pour cette hypothèse. Essayez une description
          plus détaillée, ou d&apos;autres secteurs.
        </p>
      )}
    </div>
  );
}
