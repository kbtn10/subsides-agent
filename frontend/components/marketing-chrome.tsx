"use client";

import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { Button } from "@/components/ui/button";
import { PRODUCT_NAME } from "@/lib/constants";

export function MarketingHeader() {
  const { isLoaded, isSignedIn } = useAuth();

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-bg/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-[1100px] items-center justify-between px-4 sm:px-8">
        <Link href="/" className="font-display text-xl font-semibold text-ink">
          {PRODUCT_NAME}
        </Link>
        <nav className="flex items-center gap-2">
          {isLoaded && isSignedIn ? (
            <Link href="/dashboard"><Button size="sm">Mes subsides</Button></Link>
          ) : (
            <>
              <Link href="/sign-in">
                <Button size="sm" variant="ghost">Se connecter</Button>
              </Link>
              <Link href="/sign-up">
                <Button size="sm">Créer mon profil</Button>
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}

export function MarketingFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-[1100px] flex-col gap-4 px-4 py-8 text-sm text-ink-soft sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <p>
          <span className="font-display font-semibold text-ink">{PRODUCT_NAME}</span>
          {" — "}la veille subsides des ASBL bruxelloises.
        </p>
        <nav className="flex flex-wrap gap-x-5 gap-y-2">
          <Link href="/confidentialite" className="hover:text-ink">Confidentialité</Link>
          <Link href="/sign-in" className="hover:text-ink">Se connecter</Link>
        </nav>
      </div>
    </footer>
  );
}
