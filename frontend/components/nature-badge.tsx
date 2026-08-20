import { cn } from "@/lib/utils";
import { NATURE_COURT, NATURE_ICON, type Nature } from "@/lib/nature";

/** Badge discret de nature : icône + libellé court. Rien si nature inconnue. */
export function NatureBadge({ nature, className }: { nature: Nature | null | undefined; className?: string }) {
  if (!nature) return null;
  const Icon = NATURE_ICON[nature];
  return (
    <span className={cn(
      "inline-flex items-center gap-1 rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] font-medium text-ink-soft",
      className,
    )}>
      <Icon className="h-3 w-3 shrink-0" aria-hidden /> {NATURE_COURT[nature]}
    </span>
  );
}
