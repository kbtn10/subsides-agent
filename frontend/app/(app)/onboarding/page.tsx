"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowLeft, ArrowRight, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Textarea, CheckPill } from "@/components/ui/field";
import { api, ApiError } from "@/lib/api";
import { BUDGETS, COMMUNES_19, LANGUES, PROVINCES_WALLONNES, REGIONS, SECTEURS } from "@/lib/constants";
import type { ProfilInput } from "@/lib/types";

type FormState = {
  nom: string; region: string; commune_siege: string; langue: string;
  secteurs: string[]; publics: string; budget_categorie: string;
  agrements: string; description_libre: string;
};

const VIDE: FormState = {
  nom: "", region: "bruxelles", commune_siege: COMMUNES_19[0], langue: "", secteurs: [],
  publics: "", budget_categorie: "", agrements: "", description_libre: "",
};

const ETAPES = ["Votre association", "Votre activité", "Le contexte"];

function toInput(f: FormState): ProfilInput {
  const liste = (v: string) => v.split(",").map((s) => s.trim()).filter(Boolean);
  return {
    nom: f.nom.trim(),
    region: f.region,
    commune_siege: f.commune_siege,
    langue: f.langue || null,
    secteurs: f.secteurs,
    publics_cibles: liste(f.publics),
    budget_categorie: f.budget_categorie || null,
    agrements: liste(f.agrements),
    description_libre: f.description_libre.trim() || null,
  };
}

function OnboardingInner() {
  const router = useRouter();
  const params = useSearchParams();
  const editMode = params.get("edit") === "1";
  const { getToken } = useAuth();
  const reduce = useReducedMotion();

  const [f, setF] = useState<FormState>(VIDE);
  const [etape, setEtape] = useState(0);
  const [profilId, setProfilId] = useState<number | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  // Mode édition : pré-remplir avec le profil existant.
  useEffect(() => {
    if (!editMode) return;
    (async () => {
      try {
        const profils = await api.mesProfils(getToken);
        const p = profils.find((x) => !x.ephemere) ?? profils[0];
        if (p) {
          setProfilId(p.id);
          setF({
            nom: p.nom, region: p.region ?? "bruxelles",
            commune_siege: p.commune_siege, langue: p.langue ?? "",
            secteurs: p.secteurs ?? [], publics: (p.publics_cibles ?? []).join(", "),
            budget_categorie: p.budget_categorie ?? "",
            agrements: (p.agrements ?? []).join(", "),
            description_libre: p.description_libre ?? "",
          });
        }
      } catch { /* profil neuf */ }
    })();
  }, [editMode, getToken]);

  const set = (k: keyof FormState, v: FormState[keyof FormState]) =>
    setF((prev) => ({ ...prev, [k]: v }));

  const etape1Ok = f.nom.trim().length > 0 && f.commune_siege.length > 0;

  async function soumettre() {
    setErreur(null);
    if (!etape1Ok) { setEtape(0); setErreur("Le nom et la commune sont nécessaires."); return; }
    setEnvoi(true);
    try {
      const input = toInput(f);
      const profil = profilId
        ? await api.majProfil(profilId, input, getToken)
        : await api.creerProfil(input, getToken);
      await api.lancerMatching(profil.id, getToken);
      localStorage.setItem("subsidia_profil_id", String(profil.id));
      router.push("/dashboard");
    } catch (e) {
      setErreur(e instanceof ApiError ? e.message : "Une erreur est survenue.");
      setEnvoi(false);
    }
  }

  const dir = reduce ? 0 : 1;

  return (
    <div className="py-6">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-semibold text-ink">
          {editMode ? "Modifier votre profil" : "Parlez-nous de votre association"}
        </h1>
        <p className="mt-1.5 text-ink-soft">
          Trois écrans, deux minutes. Plus vous en dites, plus l&apos;analyse est fine.
        </p>
        {/* barre de progression douce */}
        <div className="mt-5 flex items-center gap-2">
          {ETAPES.map((label, i) => (
            <div key={label} className="flex-1">
              <div className="h-1.5 overflow-hidden rounded-full bg-border">
                <motion.div
                  className="h-full bg-accent"
                  initial={false}
                  animate={{ width: i < etape ? "100%" : i === etape ? "50%" : "0%" }}
                  transition={{ duration: 0.4, ease: "easeOut" }}
                />
              </div>
              <span className={`mt-1.5 block text-xs ${i === etape ? "text-ink" : "text-ink-faint"}`}>
                {label}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-[var(--shadow-soft)]">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={etape}
            initial={{ opacity: 0, x: dir * 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: dir * -20 }}
            transition={{ duration: 0.28, ease: "easeOut" }}
          >
            {etape === 0 && (
              <div className="space-y-1">
                <Label htmlFor="nom">Nom de votre association</Label>
                <Input id="nom" value={f.nom} onChange={(e) => set("nom", e.target.value)}
                  placeholder="ex : Les Ateliers de Cureghem" autoFocus />
                <div className="pt-3">
                  <Label htmlFor="region">Région du siège</Label>
                  <Select id="region" value={f.region}
                    onChange={(e) => {
                      const region = e.target.value;
                      // En changeant de région, on remet un lieu par défaut
                      // cohérent (sinon une commune bruxelloise resterait
                      // sélectionnée pour une ASBL wallonne).
                      const lieu = region === "wallonie"
                        ? PROVINCES_WALLONNES[0] : COMMUNES_19[0];
                      setF((prev) => ({ ...prev, region, commune_siege: lieu }));
                    }}>
                    {REGIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                  </Select>
                  <p className="mt-1 text-xs text-ink-faint">
                    Détermine les subsides analysés pour vous (régionaux, FWB, fédéraux).
                  </p>
                </div>
                <div className="pt-3">
                  <Label htmlFor="commune">
                    {f.region === "wallonie" ? "Province du siège" : "Commune du siège"}
                  </Label>
                  <Select id="commune" value={f.commune_siege}
                    onChange={(e) => set("commune_siege", e.target.value)}>
                    {(f.region === "wallonie" ? PROVINCES_WALLONNES : COMMUNES_19)
                      .map((c) => <option key={c}>{c}</option>)}
                  </Select>
                </div>
                <div className="pt-3">
                  <Label htmlFor="langue" optional>Langue de fonctionnement</Label>
                  <Select id="langue" value={f.langue} onChange={(e) => set("langue", e.target.value)}>
                    <option value="">— non précisé —</option>
                    {LANGUES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
                  </Select>
                </div>
              </div>
            )}

            {etape === 1 && (
              <div className="space-y-4">
                <div>
                  <Label optional>Vos secteurs d&apos;activité</Label>
                  <div className="flex flex-wrap gap-2">
                    {SECTEURS.map((s) => (
                      <CheckPill key={s.value} checked={f.secteurs.includes(s.value)}
                        onChange={(v) => set("secteurs", v
                          ? [...f.secteurs, s.value]
                          : f.secteurs.filter((x) => x !== s.value))}>
                        {s.label}
                      </CheckPill>
                    ))}
                  </div>
                </div>
                <div>
                  <Label htmlFor="publics" optional>Vos publics cibles</Label>
                  <Input id="publics" value={f.publics} onChange={(e) => set("publics", e.target.value)}
                    placeholder="ex : jeunes, seniors, personnes en situation de handicap" />
                  <p className="mt-1 text-xs text-ink-faint">Séparés par des virgules.</p>
                </div>
              </div>
            )}

            {etape === 2 && (
              <div className="space-y-4">
                <div>
                  <Label htmlFor="budget" optional>Ordre de grandeur du budget annuel</Label>
                  <Select id="budget" value={f.budget_categorie}
                    onChange={(e) => set("budget_categorie", e.target.value)}>
                    <option value="">— non précisé —</option>
                    {BUDGETS.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
                  </Select>
                </div>
                <div>
                  <Label htmlFor="agrements" optional>Agréments / reconnaissances</Label>
                  <Input id="agrements" value={f.agrements} onChange={(e) => set("agrements", e.target.value)}
                    placeholder="ex : éducation permanente, agrément COCOF" />
                </div>
                <div>
                  <Label htmlFor="desc" optional>Décrivez votre activité</Label>
                  <Textarea id="desc" value={f.description_libre}
                    onChange={(e) => set("description_libre", e.target.value)}
                    placeholder="Nous organisons des entraînements de foot et un accompagnement scolaire pour les jeunes de Cureghem, avec 3 salariés et une quinzaine de bénévoles." />
                  <p className="mt-1.5 text-xs text-ink-faint">
                    C&apos;est le champ le plus important : plus il est précis, plus les
                    correspondances sont justes. Prenez-y quelques mots de soin.
                  </p>
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>

        {erreur && <p className="mt-4 text-sm text-danger">{erreur}</p>}

        <div className="mt-6 flex items-center justify-between gap-3">
          {etape > 0 ? (
            <Button variant="subtle" size="sm" onClick={() => setEtape((s) => s - 1)}>
              <ArrowLeft className="h-4 w-4" /> Retour
            </Button>
          ) : <span />}

          {etape < 2 ? (
            <Button
              onClick={() => { if (etape === 0 && !etape1Ok) { setErreur("Le nom et la commune sont nécessaires."); return; } setErreur(null); setEtape((s) => s + 1); }}
            >
              Continuer <ArrowRight className="h-4 w-4" />
            </Button>
          ) : (
            <Button onClick={soumettre} disabled={envoi}>
              {envoi && <Loader2 className="h-4 w-4 animate-spin" />}
              {envoi ? "On analyse…" : "Voir mes subsides"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function OnboardingPage() {
  // Le shell (app) porte déjà <Protected> : pas de double garde ici.
  return (
    <Suspense fallback={null}>
      <OnboardingInner />
    </Suspense>
  );
}
