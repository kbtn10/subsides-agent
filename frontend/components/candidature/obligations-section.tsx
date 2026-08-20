"use client";

import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import {
  AlertTriangle, CalendarClock, CheckCircle2, ChevronDown, Loader2, Megaphone,
  Plus, Quote, ShieldCheck, Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/field";
import { joursAvant } from "@/components/compact-card";
import { api } from "@/lib/api";
import type { Obligation, ObligationsEtat, TypeObligation } from "@/lib/types";
import { cn } from "@/lib/utils";

const TYPE_LABEL: Record<TypeObligation, string> = {
  justificatif: "Justificatif", rapport: "Rapport",
  communication: "Communication", autre: "Autre",
};

/** Badge d'échéance d'obligation : J-n, ambre soutenu si échu ou proche. */
function EcheanceObligation({ echeance }: { echeance: string | null }) {
  if (!echeance) {
    return <span className="rounded-md bg-surface-2 px-2 py-0.5 text-[12px] text-ink-faint">échéance à fixer</span>;
  }
  const j = joursAvant(echeance);
  const echu = j !== null && j < 0;
  const proche = j !== null && j >= 0 && j <= 14;
  return (
    <span className={cn("rounded-md px-2 py-0.5 text-[12px] font-semibold",
      echu ? "bg-amber-soft text-amber" : proche ? "bg-amber-soft text-amber" : "bg-surface-2 text-ink-soft")}>
      {echu ? `échu depuis ${-j!} j` : j === 0 ? "aujourd'hui" : `J-${j}`}
    </span>
  );
}

function LigneObligation({ o, onToggle, onSupprimer }: {
  o: Obligation; onToggle: (v: boolean) => void; onSupprimer: () => void;
}) {
  const [citation, setCitation] = useState(false);
  const fait = o.statut === "fait";
  const echu = !fait && o.echeance !== null && (joursAvant(o.echeance) ?? 0) < 0;
  return (
    <li className={cn(
      "rounded-[var(--radius-ctrl)] border p-3 transition-colors",
      fait ? "border-border bg-surface-2/60" : echu ? "border-amber/40 bg-amber-soft/40" : "border-border bg-surface",
    )}>
      <div className="flex items-start gap-2.5">
        <input type="checkbox" checked={fait} onChange={(e) => onToggle(e.target.checked)}
          aria-label={`Marquer « ${o.intitule} » comme faite`}
          className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--accent)]" />
        <div className="min-w-0 flex-1">
          <p className={cn("text-[15px] leading-snug", fait ? "text-ink-faint line-through" : "text-ink")}>
            {o.intitule}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[12px]">
            <span className="inline-flex items-center gap-1 rounded-md bg-surface-2 px-1.5 py-0.5 text-ink-soft">
              {o.type === "communication" ? <Megaphone className="h-3 w-3" aria-hidden /> : null}
              {TYPE_LABEL[o.type]}
            </span>
            <EcheanceObligation echeance={o.echeance} />
            {o.source === "manuelle" && <span className="text-ink-faint">ajoutée par vous</span>}
            {o.source_citation && (
              <button onClick={() => setCitation((v) => !v)}
                className="inline-flex items-center gap-1 text-ink-faint hover:text-ink" aria-expanded={citation}>
                <Quote className="h-3 w-3" aria-hidden /> citation
                <ChevronDown className={cn("h-3 w-3 transition-transform", citation && "rotate-180")} aria-hidden />
              </button>
            )}
          </div>
          {citation && o.source_citation && (
            <p className="mt-2 border-l-2 border-border pl-2.5 text-[13px] italic leading-relaxed text-ink-soft">
              « {o.source_citation} »
            </p>
          )}
        </div>
        <button onClick={onSupprimer} aria-label="Supprimer l'obligation"
          className="shrink-0 rounded p-1 text-ink-faint hover:bg-surface-2 hover:text-danger">
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </li>
  );
}

export function ObligationsSection({ candidatureId, initial }: {
  candidatureId: number; initial: ObligationsEtat;
}) {
  const { getToken } = useAuth();
  const [etat, setEtat] = useState<ObligationsEtat>(initial);
  const [chargement, setChargement] = useState(false);
  const [ancre, setAncre] = useState(initial.date_fin_projet ?? "");
  const [nouvelle, setNouvelle] = useState("");
  const [nvEcheance, setNvEcheance] = useState("");
  const [nvType, setNvType] = useState<TypeObligation>("autre");

  const recharger = async (forcer = false) => {
    setChargement(true);
    try { setEtat(await api.genererObligations(candidatureId, forcer, getToken)); }
    catch { /* on garde l'état courant */ }
    finally { setChargement(false); }
  };
  const toggle = async (o: Obligation, v: boolean) => {
    setEtat((s) => {
      const items = s.items.map((i) => i.id === o.id ? { ...i, statut: (v ? "fait" : "a_faire") as Obligation["statut"] } : i);
      const faites = items.filter((i) => i.statut === "fait").length;
      return { ...s, items, faites, en_regle: items.length > 0 && faites === items.length };
    });
    await api.majObligation(o.id, { fait: v }, getToken).catch(() => {});
  };
  const supprimer = async (o: Obligation) => {
    setEtat((s) => {
      const items = s.items.filter((i) => i.id !== o.id);
      const faites = items.filter((i) => i.statut === "fait").length;
      return { ...s, items, total: items.length, faites, en_regle: items.length > 0 && faites === items.length };
    });
    await api.supprimerObligation(o.id, getToken).catch(() => {});
  };
  const ancrer = async () => {
    setEtat(await api.ancrerObligations(candidatureId, ancre || null, getToken));
  };
  const ajouter = async () => {
    if (!nouvelle.trim()) return;
    const o = await api.ajouterObligation(candidatureId, nouvelle.trim(), nvEcheance || null, nvType, getToken);
    setEtat((s) => ({ ...s, items: [...s.items, o], total: s.total + 1, en_regle: false }));
    setNouvelle(""); setNvEcheance(""); setNvType("autre");
  };

  const { total, faites, en_regle } = etat;

  return (
    <section className="rounded-[var(--radius-card)] border border-border bg-surface p-5 shadow-[var(--shadow-soft)]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-display text-lg font-semibold text-ink">
          <ShieldCheck className="h-4 w-4 text-accent" aria-hidden /> Vos obligations
        </h2>
        {total > 0 && (
          <span className={cn("text-sm font-medium", en_regle ? "text-accent" : "text-ink-soft")}>
            {en_regle ? <span className="inline-flex items-center gap-1"><CheckCircle2 className="h-4 w-4" /> Dossier en règle</span>
              : `${faites}/${total} faites`}
          </span>
        )}
      </div>

      {/* Rien généré encore (échec LLM au passage en obtenu, ou pas encore lancé). */}
      {!etat.generee && !chargement && (
        <div className="mt-4 text-center">
          <p className="text-ink-soft">
            Subsidia peut relever du règlement les obligations qui suivent l&apos;octroi
            (justifications, rapports, communication, versement du solde).
          </p>
          <Button className="mt-3" size="sm" onClick={() => recharger(false)}>
            Relever mes obligations
          </Button>
        </div>
      )}

      {chargement && (
        <p className="mt-4 flex items-center gap-2 text-ink-soft">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Lecture du règlement…
        </p>
      )}

      {etat.generee && total === 0 && etat.texte_absent && (
        <p className="mt-3 rounded-[var(--radius-ctrl)] bg-surface-2 px-3 py-2.5 text-sm text-ink-soft">
          Le règlement ne détaille pas d&apos;obligation post-octroi explicite. Vérifiez la
          fiche officielle et l&apos;acte d&apos;octroi, et ajoutez vos échéances ci-dessous.
        </p>
      )}

      {etat.fiche_a_change && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-ctrl)] bg-amber-soft px-3 py-2 text-sm text-amber">
          <span>La fiche a changé depuis la dernière analyse.</span>
          <button className="font-semibold hover:underline" onClick={() => recharger(true)}>Régénérer</button>
        </div>
      )}

      {/* Ancrage : certaines obligations ont un délai relatif à la fin de projet. */}
      {etat.ancrage_requis && (
        <div className="mt-3 rounded-[var(--radius-ctrl)] border border-info/25 bg-info-soft p-3">
          <p className="flex items-center gap-2 text-sm text-info">
            <CalendarClock className="h-4 w-4 shrink-0" aria-hidden />
            Des échéances dépendent de la <span className="font-semibold">date de fin de projet</span> —
            indiquez-la pour les calculer (jamais de date inventée).
          </p>
          <div className="mt-2.5 flex flex-wrap items-end gap-2">
            <Input type="date" value={ancre} onChange={(e) => setAncre(e.target.value)}
              className="w-auto" aria-label="Date de fin de projet" />
            <Button size="sm" variant="ghost" onClick={ancrer}>Calculer les échéances</Button>
          </div>
        </div>
      )}

      {total > 0 && (
        <ul className="mt-4 space-y-2.5">
          {etat.items.map((o) => (
            <LigneObligation key={o.id} o={o}
              onToggle={(v) => toggle(o, v)} onSupprimer={() => supprimer(o)} />
          ))}
        </ul>
      )}

      {/* Une obligation échue non faite : alerte digne. */}
      {etat.items.some((o) => o.statut === "a_faire" && o.echeance && (joursAvant(o.echeance) ?? 0) < 0) && (
        <p className="mt-3 flex items-center gap-2 text-sm text-amber">
          <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
          Une échéance est passée. Un subside peut être récupéré pour justification tardive —
          contactez le subsidiant si besoin.
        </p>
      )}

      {/* Ajout manuel */}
      <div className="mt-4 border-t border-border pt-4">
        <p className="text-[13px] font-medium text-ink-soft">Ajouter une obligation</p>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <Input value={nouvelle} onChange={(e) => setNouvelle(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") ajouter(); }}
            placeholder="ex : Rapport d'activité à envoyer" className="min-w-[200px] flex-1" />
          <Input type="date" value={nvEcheance} onChange={(e) => setNvEcheance(e.target.value)}
            className="w-auto" aria-label="Échéance" />
          <Select value={nvType} onChange={(e) => setNvType(e.target.value as TypeObligation)} className="w-auto">
            {(Object.keys(TYPE_LABEL) as TypeObligation[]).map((t) => (
              <option key={t} value={t}>{TYPE_LABEL[t]}</option>
            ))}
          </Select>
          <Button size="sm" variant="ghost" onClick={ajouter} disabled={!nouvelle.trim()}>
            <Plus className="h-4 w-4" /> Ajouter
          </Button>
        </div>
      </div>
    </section>
  );
}
