"use client";
import { useEffect } from "react";
import { PRODUCT_NAME } from "./constants";

/** Titre d'onglet cohérent par page (les pages client ne peuvent pas exporter
 *  `metadata`). Restaure le titre par défaut au démontage. */
export function useTitre(titre: string) {
  useEffect(() => {
    const precedent = document.title;
    document.title = `${titre} — ${PRODUCT_NAME}`;
    return () => { document.title = precedent; };
  }, [titre]);
}
