import { Protected } from "@/components/protected";
import { BottomBar, Sidebar } from "@/components/sidebar";

// Shell de l'app authentifiée : sidebar fixe à gauche (desktop),
// barre basse (mobile). Le contenu respire jusqu'à ~1100px.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <Protected>
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="min-w-0 flex-1">
          <main className="mx-auto w-full max-w-[1100px] px-4 pb-28 pt-6 sm:px-8 lg:pb-16">
            {children}
          </main>
        </div>
        <BottomBar />
      </div>
    </Protected>
  );
}
