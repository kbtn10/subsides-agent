"use client";

import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { AlertTriangle, Check, HelpCircle, Loader2, Minus, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/field";
import { api } from "@/lib/api";
import type { Conformite } from "@/lib/types";

function Bloc({ titre, items, icone, couleur }: {
  titre: string; items: string[]; icone: React.ReactNode; couleur: string;
}) {
  if (!items.length) return null;
  return (
    <div className="mt-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">{titre}</h3>
      <ul className="mt-2 space-y-2">
        {items.map((x, i) => (
          <li key={i} className={`flex gap-2.5 text-[15px] leading-relaxed ${couleur}`}>
            <span className="mt-0.5 shrink-0" aria-hidden>{icone}</span>
            <span>{x}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ConformiteSection({ candidatureId }: { candidatureId: number }) {
  const { getToken } = useAuth();
  const [description, setDescription] = useState("");
  const [res, setRes] = useState<Conformite | null>(null);
  const [chargement, setChargement] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const verifier = async () => {
    setChargement(true); setErreur(null);
    try {
      const r = await api.verifierConformite(candidatureId, description, getToken);
      if (r.erreur) setErreur("Analyse indisponible pour le moment.");
      else setRes(r);
    } catch (e) {
      setErreur(e instanceof Error && "status" in e && (e as { status: number }).status === 429
        ? "Plafond quotidien d'analyses atteint. Réessayez demain."
        : "Analyse indisponible.");
    } finally { setChargement(false); }
  };

  return (
    <section className="rounded-[var(--radius-card)] border border-border bg-surface-2 p-5">
      <h2 className="flex items-center gap-2 font-display text-lg font-semibold text-ink">
        <ShieldCheck className="h-4 w-4 text-accent" aria-hidden /> Vérifier mon dossier
      </h2>
      <p className="mt-1 text-sm text-ink-soft">
        Décrivez où en est votre dossier (pièces réunies, points en suspens). Subsidia
        croise votre description avec le règlement — c&apos;est une aide, pas une décision.
      </p>

      <Textarea className="mt-3" value={description} onChange={(e) => setDescription(e.target.value)}
        placeholder="Ex : Nous avons les statuts et les comptes 2024. Le budget prévisionnel n'est pas finalisé. Le formulaire officiel n'est pas encore rempli." />

      <div className="mt-3 flex items-center gap-3">
        <Button size="sm" onClick={verifier} disabled={chargement}>
          {chargement ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
          Vérifier la conformité
        </Button>
        {res?.depuis_cache && <span className="text-[12px] text-ink-faint">résultat en cache</span>}
      </div>

      {erreur && <p className="mt-3 text-sm text-danger">{erreur}</p>}

      {res && (
        <div className="mt-4 rounded-[var(--radius-card)] border border-border bg-surface p-4">
          <Bloc titre="Semble en ordre" items={res.points_conformes}
            icone={<Check className="h-4 w-4 text-accent" />} couleur="text-ink" />
          <Bloc titre="Il reste à réunir" items={res.points_manquants}
            icone={<Minus className="h-4 w-4 text-amber" />} couleur="text-ink" />
          <Bloc titre="À clarifier" items={res.points_a_clarifier}
            icone={<HelpCircle className="h-4 w-4 text-[#2b6a8f]" />} couleur="text-ink" />
          <Bloc titre="Points de vigilance" items={res.avertissements}
            icone={<AlertTriangle className="h-4 w-4 text-amber" />} couleur="text-ink-soft" />
          <p className="mt-4 border-t border-border pt-3 text-[13px] text-ink-faint">
            Vérification indicative — seule l&apos;administration décide de la recevabilité.
          </p>
        </div>
      )}
    </section>
  );
}
