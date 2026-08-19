"use client";

import { useEffect, useState } from "react";
import { useAuth, useUser } from "@clerk/nextjs";
import { api } from "./api";

/**
 * Le rôle admin peut venir du JWT Clerk OU de l'allowlist serveur : seul le
 * backend connaît les deux, on le lui demande. On reste optimiste sur le
 * metadata Clerk pour éviter un clignotement du menu.
 */
export function useEstAdmin(): boolean {
  const { user } = useUser();
  const { getToken } = useAuth();
  const viaClerk = (user?.publicMetadata as { role?: string } | undefined)?.role === "admin";
  const [viaApi, setViaApi] = useState(false);

  useEffect(() => {
    if (!user) return;
    api.suisJeAdmin(getToken).then((r) => setViaApi(r.admin)).catch(() => setViaApi(false));
  }, [user, getToken]);

  return viaClerk || viaApi;
}
