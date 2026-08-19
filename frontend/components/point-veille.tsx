"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const SEUIL_H = 48;

function ilYa(iso: string): string {
  const h = Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000);
  if (h < 1) return "moins d'une heure";
  if (h < 24) return `${h} h`;
  return `${Math.floor(h / 24)} j`;
}

type Etat = { vieux: boolean; libelle: string };

/**
 * Le point de veille — l'élément signature du lot 8, et le SEUL animé en continu.
 * Vert qui respire quand les données sont fraîches ; ambre fixe (l'honnêteté
 * fait partie de la vie) quand le dernier scrape date de plus de 48 h.
 * Le halo est coupé par prefers-reduced-motion (voir globals.css).
 */
export function PointVeille({ compact = false }: { compact?: boolean }) {
  const [etat, setEtat] = useState<Etat | null>(null);

  useEffect(() => {
    // Fraîcheur calculée à la réception (hors rendu) pour rester pur.
    api.derniereMaj().then((d) => {
      const maj = d.fin;
      const vieux = !maj || (Date.now() - new Date(maj).getTime()) / 3_600_000 > SEUIL_H;
      setEtat({
        vieux,
        libelle: vieux
          ? (maj ? `Dernière vérification il y a ${ilYa(maj)}` : "Veille en attente")
          : "Veille active",
      });
    }).catch(() => setEtat({ vieux: true, libelle: "Veille en attente" }));
  }, []);

  if (!etat) return null;
  const couleur = etat.vieux ? "text-amber" : "text-accent";

  return (
    <span className={`inline-flex items-center gap-2 ${compact ? "text-[12px]" : "text-xs"}`}>
      <span className={`veille-dot inline-block h-2 w-2 rounded-full ${couleur}`}
        style={{ backgroundColor: "currentColor" }} aria-hidden />
      <span className={etat.vieux ? "text-amber" : "text-ink-soft"}>{etat.libelle}</span>
    </span>
  );
}
