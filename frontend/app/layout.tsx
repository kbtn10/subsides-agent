import type { Metadata, Viewport } from "next";
import { Fraunces, Inter } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import { PRODUCT_NAME } from "@/lib/constants";
import "./globals.css";

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  display: "swap",
  weight: ["400", "500", "600"],
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
const DESCRIPTION =
  "Décrivez votre ASBL une fois. On lit les appels à projets bruxellois à votre place " +
  "et on vous montre ceux auxquels vous êtes probablement éligible — en vous disant pourquoi.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: `${PRODUCT_NAME} — Vos subsides bruxellois`,
    template: `%s · ${PRODUCT_NAME}`,
  },
  description: DESCRIPTION,
  applicationName: PRODUCT_NAME,
  openGraph: {
    type: "website",
    locale: "fr_BE",
    siteName: PRODUCT_NAME,
    title: `${PRODUCT_NAME} — Vos subsides bruxellois`,
    description: DESCRIPTION,
  },
  twitter: { card: "summary_large_image", title: PRODUCT_NAME, description: DESCRIPTION },
};

// App claire uniquement — pas d'assombrissement auto par l'OS/navigateur.
export const viewport: Viewport = { colorScheme: "light" };

// Appearance Clerk alignée sur le design system (chaleureux, vert confiant).
const clerkAppearance = {
  variables: {
    colorPrimary: "#1e6b4e",
    colorText: "#1a1815",
    colorTextSecondary: "#6b645c",
    colorBackground: "#ffffff",
    colorInputBackground: "#ffffff",
    colorInputText: "#1a1815",
    borderRadius: "9px",
    fontFamily: "var(--font-inter), sans-serif",
  },
  elements: {
    formButtonPrimary:
      "bg-[#1e6b4e] hover:bg-[#185a41] text-white font-semibold normal-case",
    footerActionLink: "text-[#1e6b4e] hover:text-[#185a41]",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <ClerkProvider appearance={clerkAppearance}>
      <html lang="fr" className={`${fraunces.variable} ${inter.variable}`}>
        {/* Pas de header global : le shell (app) a sa sidebar, la landing son
            propre en-tête marketing. */}
        <body className="min-h-screen bg-bg text-ink antialiased">{children}</body>
      </html>
    </ClerkProvider>
  );
}
