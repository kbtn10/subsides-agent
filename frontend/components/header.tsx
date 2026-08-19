"use client";

import Link from "next/link";
import { UserButton, useAuth } from "@clerk/nextjs";
import { PRODUCT_NAME } from "@/lib/constants";

export function Header() {
  const { isLoaded, isSignedIn } = useAuth();
  return (
    <header className="sticky top-0 z-30 border-b border-border/70 bg-bg/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 w-full max-w-3xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="font-display text-xl font-semibold tracking-tight text-ink">
          {PRODUCT_NAME}
        </Link>
        <nav className="flex items-center gap-1 sm:gap-2">
          {isLoaded && isSignedIn ? (
            <>
              <Link href="/dashboard"
                className="rounded-full px-3 py-1.5 text-sm font-medium text-ink-soft transition-colors hover:bg-surface-2 hover:text-ink">
                Mes subsides
              </Link>
              <Link href="/onboarding?edit=1"
                className="rounded-full px-3 py-1.5 text-sm font-medium text-ink-soft transition-colors hover:bg-surface-2 hover:text-ink">
                Mon profil
              </Link>
              <div className="ml-1">
                <UserButton />
              </div>
            </>
          ) : isLoaded ? (
            <Link href="/sign-in"
              className="rounded-full px-3 py-1.5 text-sm font-medium text-ink-soft transition-colors hover:bg-surface-2 hover:text-ink">
              Se connecter
            </Link>
          ) : null}
        </nav>
      </div>
    </header>
  );
}
