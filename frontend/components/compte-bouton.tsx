"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useClerk, useAuth, useUser } from "@clerk/nextjs";
import { LogOut, Settings, Shield } from "lucide-react";
import { api } from "@/lib/api";
import { useEstAdmin } from "@/lib/use-admin";
import { cn } from "@/lib/utils";

function initiales(nom: string): string {
  const mots = nom.trim().split(/\s+/).filter(Boolean);
  if (!mots.length) return "?";
  if (mots.length === 1) return mots[0].slice(0, 2).toUpperCase();
  return (mots[0][0] + mots[mots.length - 1][0]).toUpperCase();
}

/**
 * Menu compte maison plutôt que <UserButton> : l'avatar Clerk par défaut est
 * un dégradé violet qui jure avec toute la palette. On garde les actions
 * Clerk (profil, déconnexion), on reprend la présentation.
 */
export function CompteBouton({ compact = false }: { compact?: boolean }) {
  const { getToken, isSignedIn } = useAuth();
  const { user } = useUser();
  const { openUserProfile, signOut } = useClerk();
  const estAdmin = useEstAdmin();

  const [nom, setNom] = useState<string | null>(null);
  const [ouvert, setOuvert] = useState(false);
  const boite = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isSignedIn) return;
    api.mesProfils(getToken)
      .then((ps) => {
        const p = ps.find((x) => !x.ephemere) ?? ps[0];
        if (p) setNom(p.nom);
      })
      .catch(() => {});
  }, [isSignedIn, getToken]);

  // Fermeture au clic extérieur et à Échap (le menu est monté dans le flux).
  useEffect(() => {
    if (!ouvert) return;
    const clic = (e: MouseEvent) => {
      if (boite.current && !boite.current.contains(e.target as Node)) setOuvert(false);
    };
    const touche = (e: KeyboardEvent) => { if (e.key === "Escape") setOuvert(false); };
    document.addEventListener("mousedown", clic);
    document.addEventListener("keydown", touche);
    return () => {
      document.removeEventListener("mousedown", clic);
      document.removeEventListener("keydown", touche);
    };
  }, [ouvert]);

  const etiquette = nom ?? user?.primaryEmailAddress?.emailAddress ?? "Mon compte";
  const pastille = (
    <span aria-hidden
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[12px] font-bold text-accent">
      {nom ? initiales(nom) : "··"}
    </span>
  );

  return (
    <div ref={boite} className="relative">
      <button
        type="button"
        onClick={() => setOuvert((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={ouvert}
        aria-label={`Compte : ${etiquette}`}
        className={cn(
          "flex w-full items-center gap-2.5 rounded-[var(--radius-ctrl)] px-2 py-1.5 text-left transition-colors hover:bg-surface-2",
          compact && "w-auto justify-center px-0 py-0 hover:bg-transparent",
        )}
      >
        {pastille}
        {!compact && (
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink" title={etiquette}>
            {etiquette}
          </span>
        )}
      </button>

      {ouvert && (
        <div role="menu"
          className={cn(
            "absolute z-50 w-56 overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface shadow-[var(--shadow-lift)]",
            compact ? "bottom-full right-0 mb-2" : "bottom-full left-0 mb-2",
          )}>
          <p className="truncate border-b border-border px-3.5 py-2.5 text-[13px] text-ink-faint">
            {user?.primaryEmailAddress?.emailAddress ?? "Connecté"}
          </p>
          {/* La barre basse mobile ne tient que 4 entrées : l'accès admin
              vit ici pour ne pas disparaître sur petit écran. */}
          {estAdmin && (
            <Link role="menuitem" href="/admin" onClick={() => setOuvert(false)}
              className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-ink hover:bg-surface-2">
              <Shield className="h-4 w-4 text-ink-faint" aria-hidden /> Administration
            </Link>
          )}
          <button role="menuitem" onClick={() => { setOuvert(false); openUserProfile(); }}
            className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-ink hover:bg-surface-2">
            <Settings className="h-4 w-4 text-ink-faint" aria-hidden /> Gérer mon compte
          </button>
          <button role="menuitem" onClick={() => signOut({ redirectUrl: "/" })}
            className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-ink hover:bg-surface-2">
            <LogOut className="h-4 w-4 text-ink-faint" aria-hidden /> Se déconnecter
          </button>
        </div>
      )}
    </div>
  );
}
