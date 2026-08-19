"use client";

import { useCallback, useEffect, useState } from "react";
import { BottomBar, Sidebar } from "@/components/sidebar";

const COOKIE = "subsidia_sidebar";

/**
 * Shell de l'app : sidebar repliable + zone de contenu FLUIDE (lot 8b).
 *
 * L'état de repli est persisté par cookie (lu côté serveur dans le layout et
 * passé en `initialReplie`) : SSR et premier rendu client concordent, donc pas
 * de flash. Raccourci clavier « [ » pour replier/déplier.
 */
export function AppShell({
  initialReplie, children,
}: { initialReplie: boolean; children: React.ReactNode }) {
  const [replie, setReplie] = useState(initialReplie);

  const basculer = useCallback(() => {
    setReplie((v) => {
      const suivant = !v;
      document.cookie = `${COOKIE}=${suivant ? "1" : "0"}; path=/; max-age=31536000; samesite=lax`;
      return suivant;
    });
  }, []);

  // Raccourci « [ » — ignoré quand on tape dans un champ.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "[" || e.metaKey || e.ctrlKey || e.altKey) return;
      const cible = e.target as HTMLElement | null;
      if (cible && /^(INPUT|TEXTAREA|SELECT)$/.test(cible.tagName)) return;
      if (cible?.isContentEditable) return;
      e.preventDefault();
      basculer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [basculer]);

  return (
    <div className="flex min-h-screen">
      <Sidebar replie={replie} onBasculer={basculer} />
      <div className="min-w-0 flex-1">
        <main className="mx-auto w-full max-w-[1680px] px-4 pb-28 pt-6 sm:px-6 lg:px-8 lg:pb-16">
          {children}
        </main>
      </div>
      <BottomBar />
    </div>
  );
}
