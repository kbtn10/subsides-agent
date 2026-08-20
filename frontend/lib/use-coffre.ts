"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/** Le coffre documentaire (lot 10A) n'existe dans l'UI que si le flag serveur
 *  COFFRE_ACTIF est true. Sans lui, aucune trace du coffre. */
export function useCoffreActif(): boolean {
  const [actif, setActif] = useState(false);
  useEffect(() => {
    api.coffreConfig().then((c) => setActif(c.actif)).catch(() => setActif(false));
  }, []);
  return actif;
}
