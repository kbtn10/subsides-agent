"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { motion, useReducedMotion } from "framer-motion";
import { AlertTriangle, Check, Clock, FileSearch, Inbox, ScanSearch } from "lucide-react";
import { Reveal } from "@/components/reveal";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { PRODUCT_NAME } from "@/lib/constants";

const ETAPES = [
  {
    icon: FileSearch,
    titre: "Vous décrivez votre ASBL",
    texte: "Commune, secteurs, publics, quelques phrases sur votre activité. Deux minutes, une seule fois.",
  },
  {
    icon: ScanSearch,
    titre: "On lit les sources officielles",
    texte: "Chaque nuit, les portails de subsides bruxellois sont relus. Les fiches nouvelles ou modifiées sont extraites telles quelles.",
  },
  {
    icon: Inbox,
    titre: "Vous recevez un tri motivé",
    texte: "Pour chaque appel : un verdict, ce qui joue en votre faveur, et ce qu'il reste à vérifier. Avec le lien vers la fiche officielle.",
  },
];

const PROBLEMES = [
  { icon: Clock, t: "Des délais courts", d: "Beaucoup d'appels laissent quatre à six semaines. Le temps de le découvrir, c'est déjà trop tard." },
  { icon: FileSearch, t: "Des critères illisibles", d: "« Agrément au sens du décret… » : il faut vingt minutes par fiche pour savoir si on est concerné." },
  { icon: AlertTriangle, t: "Aucune alerte", d: "Les portails officiels ne préviennent pas. Il faut y retourner soi-même, encore et encore." },
];

const PROMESSES = [
  "On ne dit jamais « vous êtes éligible » — seulement « probablement éligible, vérifiez ces points ».",
  "Aucun montant, aucune date, aucun critère n'est inventé. Si l'information n'est pas dans la fiche, le champ reste vide.",
  "Chaque analyse renvoie vers la fiche officielle : la source fait foi, pas nous.",
  "Les subsides qui ne vous correspondent pas vous sont montrés aussi, avec la raison.",
];

function Section({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`mx-auto max-w-[1100px] px-4 sm:px-8 ${className}`}>{children}</section>;
}

export default function Home() {
  const router = useRouter();
  const { isLoaded, isSignedIn } = useAuth();
  const reduce = useReducedMotion();
  const [stats, setStats] = useState<{ sources: number; subsides: number } | null>(null);

  // Un visiteur déjà connecté n'a rien à faire sur la page de vente.
  useEffect(() => {
    if (isLoaded && isSignedIn) router.replace("/dashboard");
  }, [isLoaded, isSignedIn, router]);

  useEffect(() => {
    Promise.all([api.sources(), api.derniereMaj()])
      .then(([s, m]) => setStats({ sources: s.filter((x) => x.actif).length, subsides: m.total_subsides }))
      .catch(() => setStats(null));
  }, []);

  // On masque la page UNIQUEMENT à un visiteur dont on sait qu'il est connecté
  // (il part vers /dashboard). Surtout pas pendant `!isLoaded` : le rendu
  // serveur passe par là, et renvoyer null y rendrait la landing vide pour les
  // moteurs de recherche comme au premier paint.
  if (isLoaded && isSignedIn) return null;

  return (
    <>
      {/* 1 — Hero */}
      <Section className="py-14 sm:py-24">
        <motion.div
          initial={reduce ? false : { opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, ease: "easeOut" }}
          className="max-w-2xl"
        >
          <span className="inline-block rounded-full bg-accent-soft px-3 py-1 text-sm font-medium text-accent">
            Pour les ASBL bruxelloises
          </span>
          <h1 className="mt-5 font-display text-4xl font-semibold leading-[1.1] text-ink sm:text-[56px]">
            {/* Césure choisie en desktop ; en 375px on laisse le texte couler. */}
            Les subsides ne vous{" "}
            <br className="hidden sm:inline" />cherchent pas. Nous, si.
          </h1>
          <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-soft">
            Décrivez votre association une fois. {PRODUCT_NAME} lit les appels à projets
            bruxellois à votre place et vous montre ceux auxquels vous êtes
            probablement éligible — en vous disant pourquoi.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/sign-up"><Button size="lg">Créer mon profil</Button></Link>
            <Link href="/sign-in"><Button size="lg" variant="ghost">J&apos;ai déjà un compte</Button></Link>
          </div>
          <p className="mt-4 text-sm text-ink-faint">
            Gratuit pendant la phase de test · Aucune carte bancaire
          </p>
        </motion.div>
      </Section>

      {/* 2 — Le problème */}
      <Section className="border-t border-border py-14 sm:py-20">
        <Reveal className="grid gap-10 lg:grid-cols-2">
          <div>
            <h2 className="font-display text-3xl font-semibold leading-tight text-ink">
              Le subside existait. Vous ne l&apos;avez jamais vu.
            </h2>
            <p className="mt-4 text-lg leading-relaxed text-ink-soft">
              Les appels à projets bruxellois sont dispersés sur une dizaine de portails,
              publiés sans préavis, formulés dans une langue administrative, et retirés
              une fois la date passée. Personne dans une petite ASBL n&apos;a le temps de
              faire cette tournée chaque semaine.
            </p>
          </div>
          <ul className="space-y-4 self-center">
            {PROBLEMES.map(({ icon: Icon, t, d }) => (
              <li key={t} className="flex gap-3.5 rounded-[var(--radius-card)] border border-border bg-surface p-4">
                <Icon className="mt-0.5 h-5 w-5 shrink-0 text-amber" aria-hidden />
                <div>
                  <p className="font-medium text-ink">{t}</p>
                  <p className="mt-0.5 text-[15px] leading-relaxed text-ink-soft">{d}</p>
                </div>
              </li>
            ))}
          </ul>
        </Reveal>
      </Section>

      {/* 3 — Comment ça marche */}
      <Section className="border-t border-border py-14 sm:py-20">
        <Reveal>
          <h2 className="font-display text-3xl font-semibold text-ink">Comment ça marche</h2>
        </Reveal>
        <div className="mt-8 grid gap-5 md:grid-cols-3">
          {ETAPES.map(({ icon: Icon, titre, texte }, i) => (
            <Reveal key={titre} delay={i * 0.08}
              className="rounded-[var(--radius-card)] border border-border bg-surface p-6">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-soft">
                <Icon className="h-5 w-5 text-accent" aria-hidden />
              </div>
              <p className="mt-4 text-xs font-semibold uppercase tracking-wide text-ink-faint">
                Étape {i + 1}
              </p>
              <h3 className="mt-1 font-display text-lg font-semibold text-ink">{titre}</h3>
              <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">{texte}</p>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* 4 — Promesse d'honnêteté */}
      <Section className="border-t border-border py-14 sm:py-20">
        <Reveal className="rounded-[var(--radius-card)] bg-accent px-6 py-10 text-white sm:px-10 sm:py-12">
          <h2 className="font-display text-3xl font-semibold leading-tight">
            Ce que nous ne ferons jamais
          </h2>
          <p className="mt-3 max-w-2xl text-lg leading-relaxed text-white/85">
            Un outil qui exagère vos chances vous fait perdre des semaines en dossiers
            perdus d&apos;avance. Nous préférons être utiles qu&apos;enthousiastes.
          </p>
          <ul className="mt-7 grid gap-3.5 sm:grid-cols-2">
            {PROMESSES.map((p) => (
              <li key={p} className="flex gap-3 text-[15px] leading-relaxed text-white/95">
                <Check className="mt-0.5 h-5 w-5 shrink-0 text-white/70" aria-hidden />
                <span>{p}</span>
              </li>
            ))}
          </ul>
        </Reveal>
      </Section>

      {/* 5 — Les sources */}
      <Section className="border-t border-border py-14 sm:py-20">
        <Reveal className="max-w-2xl">
          <h2 className="font-display text-3xl font-semibold text-ink">
            Des sources officielles, et rien d&apos;autre
          </h2>
          <p className="mt-4 text-lg leading-relaxed text-ink-soft">
            Nous relisons chaque nuit les portails publics qui publient des appels à
            projets pour les associations bruxelloises — région, commissions
            communautaires, organismes d&apos;intérêt public. Rien n&apos;est reformulé :
            les fiches sont extraites telles qu&apos;elles sont publiées, avec un lien
            vers l&apos;original.
          </p>
          {stats && (
            <div className="mt-7 flex flex-wrap gap-3">
              <div className="rounded-[var(--radius-card)] border border-border bg-surface px-5 py-4">
                <p className="font-display text-2xl font-semibold text-accent">{stats.sources}</p>
                <p className="mt-1 text-sm text-ink-soft">sources officielles surveillées</p>
              </div>
              <div className="rounded-[var(--radius-card)] border border-border bg-surface px-5 py-4">
                <p className="font-display text-2xl font-semibold text-ink">{stats.subsides}</p>
                <p className="mt-1 text-sm text-ink-soft">fiches suivies aujourd&apos;hui</p>
              </div>
            </div>
          )}
          <p className="mt-5 text-sm leading-relaxed text-ink-faint">
            Nous respectons le fichier robots.txt de chaque site, espaçons nos requêtes,
            et ne collectons aucune donnée personnelle sur ces portails.
          </p>
        </Reveal>
      </Section>

      {/* 6 — Appel final */}
      <Section className="border-t border-border py-16 sm:py-24">
        <Reveal className="max-w-2xl">
          <h2 className="font-display text-3xl font-semibold leading-tight text-ink sm:text-4xl">
            Deux minutes maintenant,
            <br />une veille pour toute l&apos;année.
          </h2>
          <p className="mt-4 text-lg text-ink-soft">
            Créez votre profil et voyez immédiatement ce qui vous correspond aujourd&apos;hui.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link href="/sign-up"><Button size="lg">Créer mon profil</Button></Link>
            <Link href="/confidentialite">
              <Button size="lg" variant="ghost">Ce qu&apos;on fait de vos données</Button>
            </Link>
          </div>
        </Reveal>
      </Section>
    </>
  );
}
