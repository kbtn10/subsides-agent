// Next.js 16 : « middleware » est renommé « proxy ». Clerk 7.5+ le supporte.
// Ici on n'impose pas de protection côté proxy (le gating est fait côté client
// via <SignedIn>/redirection, et la vraie vérification côté FastAPI). Ce proxy
// active simplement le contexte Clerk sur les routes de l'app.
import { clerkMiddleware } from "@clerk/nextjs/server";

export default clerkMiddleware();

export const config = {
  matcher: [
    // toutes les routes sauf les fichiers statiques et _next
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
