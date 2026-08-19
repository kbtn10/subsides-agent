"use client";

import { RedirectToSignIn, useAuth } from "@clerk/nextjs";
import { Loader2 } from "lucide-react";

// Gate d'authentification via hook (Clerk 7 n'exporte plus <SignedIn/>).
export function Protected({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn } = useAuth();
  if (!isLoaded) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-ink-faint">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }
  if (!isSignedIn) return <RedirectToSignIn />;
  return <>{children}</>;
}
