"use client";

import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { Loader2, ListTree, PenLine, Sparkles, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/field";
import { api } from "@/lib/api";
import type { CopiloteMessage } from "@/lib/types";

// Trois actions, et seulement trois : le copilote n'est pas un chat libre.
const ACTIONS = [
  { cle: "structurer", label: "Structurer", icon: ListTree,
    aide: "Proposer un plan de réponse aligné sur les critères — pas de texte rédigé.",
    placeholder: "Collez la question du formulaire à structurer…" },
  { cle: "relire", label: "Relire", icon: PenLine,
    aide: "Critiquer votre brouillon au regard du règlement — des annotations, pas une réécriture.",
    placeholder: "Collez votre brouillon de réponse à relire…" },
  { cle: "reformuler", label: "Reformuler", icon: Wand2,
    aide: "Améliorer la clarté d'UN paragraphe, en gardant votre fond et votre voix.",
    placeholder: "Collez le paragraphe à reformuler…" },
] as const;

export function CopiloteSection({ candidatureId, historique }: {
  candidatureId: number; historique: CopiloteMessage[];
}) {
  const { getToken } = useAuth();
  const [action, setAction] = useState<(typeof ACTIONS)[number]["cle"]>("structurer");
  const [entree, setEntree] = useState("");
  const [chargement, setChargement] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [fil, setFil] = useState<CopiloteMessage[]>(historique);

  const meta = ACTIONS.find((a) => a.cle === action)!;

  const lancer = async () => {
    if (!entree.trim()) return;
    setChargement(true); setErreur(null);
    try {
      const r = await api.copilote(candidatureId, action, entree.trim(), getToken);
      if (r.erreur) { setErreur("Assistance indisponible pour le moment."); return; }
      setFil((f) => [...f, { action, entree: entree.trim(), sortie: r.sortie, cree_le: "" }]);
      setEntree("");
    } catch (e) {
      setErreur(e instanceof Error && "status" in e && (e as { status: number }).status === 429
        ? "Plafond quotidien d'analyses atteint. Réessayez demain."
        : "Assistance indisponible.");
    } finally { setChargement(false); }
  };

  return (
    <section className="rounded-[var(--radius-card)] border border-border bg-surface-2 p-5">
      <h2 className="flex items-center gap-2 font-display text-lg font-semibold text-ink">
        <Sparkles className="h-4 w-4 text-accent" aria-hidden /> Copilote de rédaction
      </h2>
      <p className="mt-1 text-sm text-ink-soft">
        Une aide à la relecture, jamais un rédacteur. Vous restez l&apos;auteur.
      </p>

      {/* Les trois actions, nommées explicitement (pas de chat ouvert). */}
      <div className="mt-3 flex flex-wrap gap-2">
        {ACTIONS.map((a) => {
          const Icon = a.icon;
          return (
            <button key={a.cle} onClick={() => setAction(a.cle)}
              className={`inline-flex items-center gap-1.5 rounded-[var(--radius-ctrl)] border px-3 py-1.5 text-sm transition-colors ${
                action === a.cle ? "border-accent bg-accent-soft font-semibold text-accent"
                  : "border-border text-ink-soft hover:border-border-strong"}`}>
              <Icon className="h-4 w-4" aria-hidden /> {a.label}
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-[13px] text-ink-faint">{meta.aide}</p>

      <Textarea className="mt-2" value={entree} onChange={(e) => setEntree(e.target.value)}
        placeholder={meta.placeholder} />
      <div className="mt-2">
        <Button size="sm" onClick={lancer} disabled={chargement}>
          {chargement ? <Loader2 className="h-4 w-4 animate-spin" /> : <meta.icon className="h-4 w-4" />}
          {meta.label}
        </Button>
      </div>
      {erreur && <p className="mt-3 text-sm text-danger">{erreur}</p>}

      {fil.length > 0 && (
        <div className="mt-5 space-y-4">
          {fil.map((m, i) => (
            <div key={i} className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
              <p className="text-[12px] font-semibold uppercase tracking-wide text-ink-faint">
                {ACTIONS.find((a) => a.cle === m.action)?.label ?? m.action}
              </p>
              <p className="mt-1 border-l-2 border-border pl-3 text-[13px] text-ink-soft line-clamp-3">
                {m.entree}
              </p>
              <p className="mt-3 whitespace-pre-wrap text-[15px] leading-relaxed text-ink">{m.sortie}</p>
              <p className="mt-3 border-t border-border pt-2 text-[12px] italic text-ink-faint">
                Relecture d&apos;aide — vous restez l&apos;auteur de votre dossier.
              </p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
