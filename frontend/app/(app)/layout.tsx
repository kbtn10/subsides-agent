import { cookies } from "next/headers";
import { Protected } from "@/components/protected";
import { AppShell } from "@/components/app-shell";
import { ToastProvider } from "@/components/toast";

// Shell de l'app authentifiée : sidebar repliable (desktop) + contenu fluide.
// L'état de repli est lu côté serveur (cookie) pour éviter tout flash.
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const replie = (await cookies()).get("subsidia_sidebar")?.value === "1";
  return (
    <Protected>
      <ToastProvider>
        <AppShell initialReplie={replie}>{children}</AppShell>
      </ToastProvider>
    </Protected>
  );
}
