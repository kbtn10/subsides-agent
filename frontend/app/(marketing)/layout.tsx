import { MarketingFooter, MarketingHeader } from "@/components/marketing-chrome";

// Pages publiques : en-tête marketing + pied de page. Pas de sidebar ici —
// un visiteur non connecté n'a rien à naviguer dans l'app.
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <MarketingHeader />
      <main className="flex-1">{children}</main>
      <MarketingFooter />
    </div>
  );
}
