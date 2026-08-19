import Link from "next/link";
import { Button } from "@/components/ui/button";

// Page 404 aux couleurs de l'app (la 404 par défaut de Next ignore le design system
// et s'affiche en sombre — ce qui donne l'impression que l'app est cassée).
export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-start justify-center gap-4 py-12">
      <p className="font-display text-5xl font-semibold text-ink-faint">404</p>
      <h1 className="font-display text-2xl font-semibold text-ink">
        Cette page n&apos;existe pas
      </h1>
      <p className="max-w-md text-ink-soft">
        Le lien que vous avez suivi ne mène nulle part. Vos subsides, eux, sont
        toujours là.
      </p>
      <div className="flex flex-wrap gap-3 pt-2">
        <Link href="/dashboard">
          <Button>Voir mes subsides</Button>
        </Link>
        <Link href="/">
          <Button variant="ghost">Retour à l&apos;accueil</Button>
        </Link>
      </div>
    </div>
  );
}
