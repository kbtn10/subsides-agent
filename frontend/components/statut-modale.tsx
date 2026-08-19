"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/field";
import { STATUT_LABEL } from "@/lib/constants";
import type { Candidature, StatutCandidature } from "@/lib/types";

type Patch = {
  date_soumission?: string; date_decision?: string;
  montant_demande?: string; montant_obtenu?: string;
};

/**
 * Modale légère à l'entrée dans un statut qui appelle une info. TOUT est
 * optionnel sauf le statut lui-même : on peut valider à vide (« Passer sans
 * préciser »). On n'oblige jamais l'utilisateur à inventer une date.
 */
export function StatutModale({
  candidature, statut, onFermer, onValider,
}: {
  candidature: Candidature;
  statut: StatutCandidature;
  onFermer: () => void;
  onValider: (patch: Patch) => Promise<void>;
}) {
  const aujourdhui = new Date().toISOString().slice(0, 10);
  const [dateSoumission, setDateSoumission] = useState(aujourdhui);
  const [dateDecision, setDateDecision] = useState(aujourdhui);
  const [montantDemande, setMontantDemande] = useState(
    candidature.montant_demande ? String(candidature.montant_demande) : "");
  const [montantObtenu, setMontantObtenu] = useState("");
  const [envoi, setEnvoi] = useState(false);

  useEffect(() => {
    const echap = (e: KeyboardEvent) => { if (e.key === "Escape") onFermer(); };
    document.addEventListener("keydown", echap);
    return () => document.removeEventListener("keydown", echap);
  }, [onFermer]);

  const valider = async (patch: Patch) => {
    setEnvoi(true);
    try { await onValider(patch); } finally { setEnvoi(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-4"
      onClick={onFermer}>
      <div onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm rounded-[var(--radius-card)] border border-border bg-surface p-5 shadow-[var(--shadow-lift)]">
        <h2 className="font-display text-lg font-semibold text-ink">
          Passer en « {STATUT_LABEL[statut]} »
        </h2>

        <div className="mt-4 space-y-4">
          {statut === "soumis" && (
            <>
              <div>
                <Label htmlFor="ds" optional>Date de soumission</Label>
                <Input id="ds" type="date" value={dateSoumission}
                  onChange={(e) => setDateSoumission(e.target.value)} />
              </div>
              <div>
                <Label htmlFor="md" optional>Montant demandé (€)</Label>
                <Input id="md" inputMode="numeric" placeholder="ex : 3000"
                  value={montantDemande} onChange={(e) => setMontantDemande(e.target.value)} />
              </div>
            </>
          )}
          {(statut === "obtenu" || statut === "refuse") && (
            <>
              <div>
                <Label htmlFor="dd" optional>Date de décision</Label>
                <Input id="dd" type="date" value={dateDecision}
                  onChange={(e) => setDateDecision(e.target.value)} />
              </div>
              {statut === "obtenu" && (
                <div>
                  <Label htmlFor="mo" optional>Montant obtenu (€)</Label>
                  <Input id="mo" inputMode="numeric" placeholder="ex : 2500"
                    value={montantObtenu} onChange={(e) => setMontantObtenu(e.target.value)} />
                </div>
              )}
            </>
          )}
        </div>

        <div className="mt-5 flex items-center justify-between gap-3">
          <button onClick={() => valider({})} disabled={envoi}
            className="text-sm text-ink-soft hover:text-ink">
            Passer sans préciser
          </button>
          <div className="flex gap-2">
            <Button variant="subtle" size="sm" onClick={onFermer} disabled={envoi}>Annuler</Button>
            <Button size="sm" disabled={envoi} onClick={() => valider(
              statut === "soumis"
                ? { date_soumission: dateSoumission, montant_demande: montantDemande || undefined }
                : statut === "obtenu"
                  ? { date_decision: dateDecision, montant_obtenu: montantObtenu || undefined }
                  : { date_decision: dateDecision })}>
              Enregistrer
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
