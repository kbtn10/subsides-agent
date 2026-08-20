"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import {
  CheckCircle2, ChevronDown, Clock, Download, FileText, History, Loader2,
  ShieldCheck, Trash2, Upload,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import { useToast } from "@/components/toast";
import { useTitre } from "@/lib/use-titre";
import { api, ApiError } from "@/lib/api";
import { resoudreProfilId } from "@/lib/profil-courant";
import type { CoffreCategorie, CoffreEtat, CoffreVersion } from "@/lib/types";
import { cn } from "@/lib/utils";

function koctets(n: number) {
  return n < 1024 ? `${n} o` : n < 1024 * 1024 ? `${Math.round(n / 1024)} Ko` : `${(n / 1048576).toFixed(1)} Mo`;
}

/** Pastille de fraîcheur : verte (à jour) / ambre (expire) / grise (à renouveler / vide). */
function Pastille({ cat }: { cat: CoffreCategorie }) {
  if (!cat.document) {
    return <span className="inline-flex items-center gap-1.5 text-[13px] text-ink-faint">
      <span className="h-2 w-2 rounded-full bg-border-strong" aria-hidden /> pas encore déposé
    </span>;
  }
  const e = cat.fraicheur?.etat;
  const map = {
    a_jour: { dot: "bg-accent", txt: "text-accent" },
    expire_bientot: { dot: "bg-amber", txt: "text-amber" },
    a_renouveler: { dot: "bg-neutral", txt: "text-ink-soft" },
  } as const;
  const s = map[e ?? "a_jour"];
  return <span className={cn("inline-flex items-center gap-1.5 text-[13px] font-medium", s.txt)}>
    <span className={cn("h-2 w-2 rounded-full", s.dot)} aria-hidden /> {cat.fraicheur?.message ?? "à jour"}
  </span>;
}

function CategorieCard({ profilId, cat, onChange }: {
  profilId: number; cat: CoffreCategorie; onChange: () => void;
}) {
  const { getToken } = useAuth();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [envoi, setEnvoi] = useState(false);
  const [dateChamp, setDateChamp] = useState("");
  const [versions, setVersions] = useState<CoffreVersion[] | null>(null);
  const [confirmer, setConfirmer] = useState(false);
  const estAgrement = cat.id === "agrement";

  const televerser = async (file: File) => {
    setEnvoi(true);
    try {
      const form = new FormData();
      form.append("fichier", file);
      form.append("categorie", cat.id);
      form.append("nom_affiche", file.name);
      if (dateChamp) form.append(estAgrement ? "expire_le" : "date_document", dateChamp);
      await api.uploaderDocument(profilId, form, getToken);
      setDateChamp("");
      onChange();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Dépôt refusé.");
    } finally { setEnvoi(false); }
  };
  const supprimer = async () => {
    if (!cat.document) return;
    setConfirmer(false);
    await api.supprimerDocument(cat.document.id, getToken).catch(() => {});
    onChange();
  };
  const telecharger = async () => {
    if (!cat.document) return;
    await api.telechargerDocument(cat.document.id, cat.document.nom_fichier ?? cat.document.nom_affiche, getToken)
      .catch(() => toast("Téléchargement impossible."));
  };
  const voirVersions = async () => {
    if (versions) { setVersions(null); return; }
    const d = await api.coffreVersions(profilId, cat.id, getToken).catch(() => ({ versions: [] }));
    setVersions(d.versions);
  };

  return (
    <div className="flex flex-col rounded-[var(--radius-card)] border border-border bg-surface p-4 shadow-[var(--shadow-soft)]">
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-display text-[15px] font-semibold text-ink">{cat.label}</h3>
        <Pastille cat={cat} />
      </div>

      {cat.document ? (
        <div className="mt-2 min-w-0 flex-1">
          <p className="flex items-center gap-1.5 truncate text-[14px] text-ink">
            <FileText className="h-4 w-4 shrink-0 text-ink-faint" aria-hidden />
            {cat.document.nom_affiche}
          </p>
          <p className="mt-0.5 text-[12px] text-ink-faint">
            {cat.document.date_document ? <>daté du {cat.document.date_document} · </> : null}
            {koctets(cat.document.taille)}
            {cat.document.expire_le ? <> · expire le {cat.document.expire_le}</> : null}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <button onClick={telecharger}
              className="inline-flex items-center gap-1 rounded-[var(--radius-ctrl)] border border-border px-2 py-1 text-[12px] text-ink-soft hover:bg-surface-2 hover:text-ink">
              <Download className="h-3.5 w-3.5" /> Télécharger
            </button>
            {cat.versions_count > 0 && (
              <button onClick={voirVersions} aria-expanded={!!versions}
                className="inline-flex items-center gap-1 rounded-[var(--radius-ctrl)] border border-border px-2 py-1 text-[12px] text-ink-soft hover:bg-surface-2 hover:text-ink">
                <History className="h-3.5 w-3.5" /> {cat.versions_count} version{cat.versions_count > 1 ? "s" : ""}
                <ChevronDown className={cn("h-3 w-3 transition-transform", versions && "rotate-180")} />
              </button>
            )}
            <button onClick={() => setConfirmer(true)} aria-label="Supprimer"
              className="inline-flex items-center gap-1 rounded-[var(--radius-ctrl)] border border-border px-2 py-1 text-[12px] text-ink-soft hover:bg-surface-2 hover:text-danger">
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
          {versions && (
            <ul className="mt-2 space-y-1 border-l-2 border-border pl-2.5 text-[12px] text-ink-soft">
              {versions.map((v) => (
                <li key={v.id} className="flex items-center justify-between gap-2">
                  <span className="truncate">{v.nom_affiche} · {koctets(v.taille)}</span>
                  <span className="shrink-0 text-ink-faint">{v.courant ? "actuel" : "archive"}</span>
                </li>
              ))}
            </ul>
          )}
          {confirmer && (
            <div className="mt-2 flex items-center gap-2 rounded-[var(--radius-ctrl)] bg-surface-2 px-2.5 py-2 text-[12px]">
              <span className="text-ink">Supprimer définitivement ?</span>
              <button onClick={() => setConfirmer(false)} className="font-medium text-ink-soft hover:text-ink">Annuler</button>
              <button onClick={supprimer} className="font-semibold text-danger hover:underline">Supprimer</button>
            </div>
          )}
        </div>
      ) : (
        <p className="mt-2 flex-1 text-[13px] text-ink-soft">
          Déposez ce document pour le garder à portée de main lors de vos candidatures.
        </p>
      )}

      {/* Dépôt / remplacement */}
      <div className="mt-3 border-t border-border pt-3">
        <div className="flex flex-wrap items-center gap-2">
          <input ref={fileRef} type="file" className="hidden"
            accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) televerser(f); e.target.value = ""; }} />
          <Input type="date" value={dateChamp} onChange={(e) => setDateChamp(e.target.value)}
            className="w-auto" aria-label={estAgrement ? "Échéance de l'agrément" : "Date du document"}
            title={estAgrement ? "Échéance de l'agrément" : "Date du document (facultatif)"} />
          <Button size="sm" variant={cat.document ? "ghost" : "primary"}
            onClick={() => fileRef.current?.click()} disabled={envoi}>
            {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {cat.document ? "Remplacer" : "Déposer"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function CoffrePage() {
  useTitre("Mon coffre");
  const router = useRouter();
  const { getToken } = useAuth();
  const [pid, setPid] = useState<number | null>(null);
  const [etat, setEtat] = useState<CoffreEtat | null>(null);
  const [erreur, setErreur] = useState(false);

  const charger = useCallback(async (p: number) => {
    setEtat(await api.coffre(p, getToken));
  }, [getToken]);

  useEffect(() => {
    (async () => {
      let p: number | null;
      try { p = await resoudreProfilId(getToken); }
      catch { setErreur(true); return; }
      if (p == null) { router.replace("/onboarding"); return; }
      setPid(p);
      try { await charger(p); }
      catch (e) {
        // Flag off (403) : le coffre n'existe pas -> retour au dashboard.
        if (e instanceof ApiError && e.status === 403) { router.replace("/dashboard"); return; }
        setErreur(true);
      }
    })();
  }, [router, getToken, charger]);

  if (erreur) {
    return <div className="py-16 text-center">
      <h1 className="font-display text-2xl font-semibold text-ink">Coffre indisponible</h1>
      <p className="mt-2 text-ink-soft">Réessayez dans un instant.</p>
    </div>;
  }
  if (!etat || pid == null) {
    return <p className="flex items-center gap-2 py-10 text-ink-soft">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Chargement…
    </p>;
  }

  return (
    <div>
      <header className="mb-6">
        <h1 className="flex items-center gap-2 font-display text-3xl font-semibold text-ink">
          <ShieldCheck className="h-6 w-6 text-accent" aria-hidden /> Mon coffre
        </h1>
        <p className="mt-1 text-ink-soft">
          Vos documents d&apos;association, chiffrés et prêts à l&apos;emploi pour vos candidatures.
          {" "}Rien n&apos;est partagé sans vous.
        </p>
        <div className="mt-3 flex flex-wrap gap-4 text-sm">
          <span className="inline-flex items-center gap-1.5 text-accent">
            <CheckCircle2 className="h-4 w-4" aria-hidden /> {etat.a_jour} à jour
          </span>
          {etat.a_renouveler > 0 && (
            <span className="inline-flex items-center gap-1.5 text-amber">
              <Clock className="h-4 w-4" aria-hidden /> {etat.a_renouveler} à renouveler
            </span>
          )}
          <span className="text-ink-faint">{etat.total}/{etat.max} documents</span>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-3 min-[900px]:grid-cols-2 min-[1400px]:grid-cols-3">
        {etat.categories.map((c) => (
          <CategorieCard key={c.id} profilId={pid} cat={c} onChange={() => charger(pid)} />
        ))}
      </div>
    </div>
  );
}
