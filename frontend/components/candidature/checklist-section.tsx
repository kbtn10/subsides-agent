"use client";

import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { ChevronDown, FileText, Loader2, Plus, Quote, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import { api } from "@/lib/api";
import type { ChecklistEtat, ChecklistItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const TYPE_LABEL: Record<string, string> = {
  document: "Document", formulaire: "Formulaire", condition_forme: "Condition de forme",
};

function Item({ item, onToggle, onSupprimer }: {
  item: ChecklistItem; onToggle: (v: boolean) => void; onSupprimer: () => void;
}) {
  const [citVisible, setCitVisible] = useState(false);
  return (
    <li className="rounded-[var(--radius-ctrl)] border border-border bg-surface p-3">
      <div className="flex items-start gap-3">
        <input type="checkbox" checked={item.coche === 1}
          onChange={(e) => onToggle(e.target.checked)}
          className="mt-1 h-4 w-4 shrink-0 accent-[var(--accent)]" />
        <div className="min-w-0 flex-1">
          <p className={cn("text-[15px] text-ink", item.coche === 1 && "text-ink-faint line-through")}>
            {item.intitule}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px]">
            <span className="rounded bg-surface-2 px-1.5 py-0.5 text-ink-soft">{TYPE_LABEL[item.type]}</span>
            {item.origine === "utilisateur" && <span className="text-ink-faint">ajouté par vous</span>}
            {item.source_citation && (
              <button onClick={() => setCitVisible((v) => !v)}
                className="inline-flex items-center gap-1 text-accent hover:underline">
                <Quote className="h-3 w-3" aria-hidden /> source
                <ChevronDown className={cn("h-3 w-3 transition-transform", citVisible && "rotate-180")} />
              </button>
            )}
          </div>
          {citVisible && item.source_citation && (
            <p className="mt-2 border-l-2 border-border-strong pl-3 text-[13px] italic leading-relaxed text-ink-soft">
              « {item.source_citation} »
            </p>
          )}
        </div>
        <button onClick={onSupprimer} aria-label="Supprimer"
          className="shrink-0 text-ink-faint hover:text-danger">
          <Trash2 className="h-4 w-4" aria-hidden />
        </button>
      </div>
    </li>
  );
}

export function ChecklistSection({ candidatureId, initial }: {
  candidatureId: number; initial: ChecklistEtat;
}) {
  const { getToken } = useAuth();
  const [etat, setEtat] = useState<ChecklistEtat>(initial);
  const [chargement, setChargement] = useState(false);
  const [nouvel, setNouvel] = useState("");

  const recharger = async (forcer = false) => {
    setChargement(true);
    try { setEtat(await api.genererChecklist(candidatureId, forcer, getToken)); }
    catch (e) {
      const msg = e instanceof Error && "status" in e && (e as { status: number }).status === 429
        ? "Plafond quotidien d'analyses atteint. Réessayez demain." : "Analyse indisponible.";
      setEtat((s) => ({ ...s, erreur: msg }));
    } finally { setChargement(false); }
  };

  const toggle = async (item: ChecklistItem, v: boolean) => {
    setEtat((s) => ({ ...s, items: s.items.map((i) =>
      i.id === item.id ? { ...i, coche: v ? 1 : 0 } : i) }));
    await api.cocherItem(item.id, v, getToken).catch(() => {});
  };
  const supprimer = async (item: ChecklistItem) => {
    setEtat((s) => ({ ...s, items: s.items.filter((i) => i.id !== item.id) }));
    await api.supprimerItem(item.id, getToken).catch(() => {});
  };
  const ajouter = async () => {
    if (!nouvel.trim()) return;
    const it = await api.ajouterItem(candidatureId, nouvel.trim(), getToken);
    setEtat((s) => ({ ...s, items: [...s.items, it] }));
    setNouvel("");
  };

  const total = etat.items.length;
  const coches = etat.items.filter((i) => i.coche === 1).length;

  return (
    <section className="rounded-[var(--radius-card)] border border-border bg-surface-2 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-display text-lg font-semibold text-ink">
          <FileText className="h-4 w-4 text-accent" aria-hidden /> Pièces du dossier
        </h2>
        {total > 0 && <span className="text-sm text-ink-soft">{coches}/{total} prêtes</span>}
      </div>

      {!etat.generee && !chargement && (
        <div className="mt-4 text-center">
          <p className="text-ink-soft">
            Subsidia peut lister les pièces exigées par le règlement, avec la citation
            d&apos;où chacune vient.
          </p>
          <Button className="mt-3" size="sm" onClick={() => recharger(false)}>
            <Sparkles className="h-4 w-4" /> Générer la checklist
          </Button>
        </div>
      )}

      {chargement && (
        <p className="mt-4 flex items-center gap-2 text-ink-soft">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Lecture du règlement…
        </p>
      )}

      {etat.erreur && <p className="mt-3 text-sm text-danger">{etat.erreur}</p>}

      {etat.generee && etat.fiche_a_change && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-ctrl)] bg-amber-soft px-3 py-2 text-sm text-amber">
          <span>La fiche a changé depuis la dernière génération.</span>
          <button onClick={() => recharger(true)} className="inline-flex items-center gap-1 font-semibold hover:underline">
            <RefreshCw className="h-3.5 w-3.5" /> Mettre à jour (vos coches sont conservées)
          </button>
        </div>
      )}

      {etat.generee && total === 0 && etat.texte_absent && (
        <p className="mt-4 rounded-[var(--radius-ctrl)] border border-border bg-surface p-4 text-[15px] text-ink-soft">
          Le règlement ne détaille pas les pièces à fournir. Consultez la fiche officielle
          pour la liste exacte — et ajoutez ci-dessous vos propres éléments de suivi.
        </p>
      )}

      {total > 0 && (
        <ul className="mt-4 space-y-2">
          {etat.items.map((it) => (
            <Item key={it.id} item={it}
              onToggle={(v) => toggle(it, v)} onSupprimer={() => supprimer(it)} />
          ))}
        </ul>
      )}

      {etat.generee && (
        <div className="mt-3 flex gap-2">
          <Input placeholder="Ajouter une pièce de votre suivi…" value={nouvel}
            onChange={(e) => setNouvel(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") ajouter(); }} />
          <Button variant="subtle" size="sm" onClick={ajouter}><Plus className="h-4 w-4" /></Button>
        </div>
      )}
    </section>
  );
}
