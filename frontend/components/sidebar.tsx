"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarClock, ClipboardList, LayoutGrid, PanelLeftClose,
  PanelLeftOpen, Search, Shield, UserCog } from "lucide-react";
import { api } from "@/lib/api";
import { useEstAdmin } from "@/lib/use-admin";
import { PRODUCT_NAME } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { CompteBouton } from "./compte-bouton";
import { PointVeille } from "./point-veille";

const NAV = [
  { href: "/dashboard", label: "Mes subsides", icon: LayoutGrid },
  { href: "/candidatures", label: "Mes candidatures", icon: ClipboardList },
  { href: "/echeances", label: "Échéances", icon: CalendarClock },
  { href: "/recherche", label: "Recherche libre", icon: Search },
  { href: "/onboarding?edit=1", label: "Mon profil", icon: UserCog, match: "/onboarding" },
];

/** Barre latérale desktop (>= lg), repliable en rail d'icônes (lot 8b). */
export function Sidebar({ replie, onBasculer }: { replie: boolean; onBasculer: () => void }) {
  const pathname = usePathname();
  const estAdmin = useEstAdmin();
  const [nbSources, setNbSources] = useState<number | null>(null);

  useEffect(() => {
    api.sources()
      .then((s) => setNbSources(s.filter((x) => x.actif).length))
      .catch(() => setNbSources(null));
  }, []);

  const lien = (href: string, label: string, Icon: typeof LayoutGrid, match?: string) => {
    const actif = pathname === href.split("?")[0] || (match ? pathname.startsWith(match) : false);
    return (
      <Link
        key={href}
        href={href}
        aria-current={actif ? "page" : undefined}
        title={replie ? label : undefined}
        className={cn(
          "flex items-center gap-3 rounded-[var(--radius-ctrl)] text-[15px] transition-colors",
          replie ? "justify-center px-0 py-2.5" : "px-3 py-2.5",
          actif
            ? "bg-accent-soft font-semibold text-accent"
            : "text-ink-soft hover:bg-surface-2 hover:text-ink",
        )}
      >
        <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />
        {!replie && <span className="truncate">{label}</span>}
      </Link>
    );
  };

  return (
    // sticky + h-screen : la nav reste visible quand la liste défile. Largeur
    // animée entre le rail (64px) et l'état complet (240px).
    <aside className={cn(
      "hidden lg:sticky lg:top-0 lg:flex lg:h-screen lg:shrink-0 lg:flex-col lg:overflow-hidden",
      "lg:border-r lg:border-border lg:bg-sidebar lg:transition-[width] lg:duration-200 lg:ease-out",
      replie ? "lg:w-16" : "lg:w-[240px]",
    )}>
      <div className={cn("flex h-16 items-center", replie ? "justify-center px-0" : "justify-between px-5")}>
        {!replie && (
          <Link href="/dashboard" className="font-display text-xl font-semibold text-ink">
            {PRODUCT_NAME}
          </Link>
        )}
        <button
          onClick={onBasculer}
          aria-label={replie ? "Déplier la barre latérale" : "Replier la barre latérale"}
          aria-expanded={!replie}
          title={`${replie ? "Déplier" : "Replier"} la barre latérale  ( [ )`}
          className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-ctrl)] text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
        >
          {replie
            ? <PanelLeftOpen className="h-[18px] w-[18px]" aria-hidden />
            : <PanelLeftClose className="h-[18px] w-[18px]" aria-hidden />}
        </button>
      </div>
      <nav className={cn("flex flex-1 flex-col gap-1 py-2", replie ? "px-2" : "px-3")}>
        {NAV.map((n) => lien(n.href, n.label, n.icon, n.match))}
        {estAdmin && lien("/admin", "Admin", Shield)}
      </nav>
      <div className={cn("border-t border-border py-3", replie ? "px-2" : "px-3")}>
        {replie ? (
          <div className="flex flex-col items-center gap-3">
            <CompteBouton compact />
            <span className="text-accent" title="Veille active"><PointVeille railOnly /></span>
          </div>
        ) : (
          <>
            <CompteBouton />
            <div className="mt-3 flex flex-col gap-1.5 px-2">
              <PointVeille />
              <p className="text-xs leading-relaxed text-ink-faint">
                {nbSources ?? "—"} sources officielles surveillées
              </p>
            </div>
          </>
        )}
      </div>
    </aside>
  );
}

/** Barre de navigation basse (mobile). Choix assumé vs burger : une cible au
 *  pouce, toujours visible, sans geste d'ouverture. */
export function BottomBar() {
  const pathname = usePathname();
  const estAdmin = useEstAdmin();
  const items = [...NAV, ...(estAdmin ? [{ href: "/admin", label: "Admin", icon: Shield, match: undefined }] : [])];

  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-border bg-surface/95 backdrop-blur-md lg:hidden">
      {items.slice(0, 4).map(({ href, label, icon: Icon, match }) => {
        const actif = pathname === href.split("?")[0] || (match ? pathname.startsWith(match) : false);
        return (
          <Link
            key={href}
            href={href}
            aria-current={actif ? "page" : undefined}
            className={cn(
              "flex flex-1 flex-col items-center gap-1 px-1 py-2.5 text-[11px] transition-colors",
              actif ? "font-semibold text-accent" : "text-ink-soft",
            )}
          >
            <Icon className="h-5 w-5" aria-hidden />
            <span className="truncate">{label}</span>
          </Link>
        );
      })}
      <div className="flex flex-1 flex-col items-center justify-center px-1 py-2.5">
        <CompteBouton compact />
      </div>
    </nav>
  );
}
