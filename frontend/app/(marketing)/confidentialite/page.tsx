import type { Metadata } from "next";
import Link from "next/link";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `Confidentialité — ${PRODUCT_NAME}`,
  description: "Ce que nous collectons, pourquoi, et ce que nous ne faisons pas de vos données.",
};

function Bloc({ titre, children }: { titre: string; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="font-display text-xl font-semibold text-ink">{titre}</h2>
      <div className="mt-2 space-y-3 text-[16px] leading-relaxed text-ink-soft">{children}</div>
    </section>
  );
}

export default function ConfidentialitePage() {
  return (
    <div className="mx-auto max-w-[720px] px-4 py-14 sm:px-8">
      <h1 className="font-display text-4xl font-semibold text-ink">Vos données</h1>
      <p className="mt-3 text-lg text-ink-soft">
        En une phrase : nous stockons ce que vous nous dites de votre association pour
        pouvoir la comparer aux appels à projets, et rien d&apos;autre.
      </p>

      <Bloc titre="Ce que nous collectons">
        <p>
          Le profil que vous remplissez : nom de l&apos;association, commune du siège,
          langue, secteurs, publics cibles, ordre de grandeur du budget, agréments, et
          votre description libre. Plus votre adresse e-mail, gérée par notre prestataire
          d&apos;authentification.
        </p>
        <p>
          Nous conservons aussi les analyses produites pour votre profil, afin de ne pas
          les recalculer à chaque visite.
        </p>
      </Bloc>

      <Bloc titre="Pourquoi">
        <p>
          Uniquement pour comparer votre situation aux critères des appels à projets
          publics et vous présenter un tri motivé. Aucune autre finalité.
        </p>
      </Bloc>

      <Bloc titre="Le rôle de l'analyse automatique">
        <p>
          Le contenu de votre profil est transmis à un modèle de langage (Anthropic) pour
          produire le raisonnement d&apos;éligibilité. Ces données ne servent pas à
          entraîner de modèle. Le verdict affiché est une aide à la décision : il ne vaut
          jamais confirmation d&apos;éligibilité, seule l&apos;administration compétente
          peut la donner.
        </p>
      </Bloc>

      <Bloc titre="Ce que nous ne faisons pas">
        <p>
          Nous ne revendons ni ne partageons votre profil. Nous n&apos;affichons pas de
          publicité. Nous ne pistons pas votre navigation à des fins commerciales.
        </p>
      </Bloc>

      <Bloc titre="Les sources publiques">
        <p>
          Les fiches de subsides proviennent de portails publics. Nous respectons leur
          fichier robots.txt, espaçons nos requêtes pour ne pas les surcharger, et
          n&apos;y collectons aucune donnée personnelle.
        </p>
      </Bloc>

      <Bloc titre="Vos droits">
        <p>
          Vous pouvez modifier votre profil à tout moment, ou demander sa suppression :
          la suppression du profil efface aussi les analyses associées. Les recherches
          libres créent un profil temporaire, effacé automatiquement au bout de 7 jours.
        </p>
      </Bloc>

      <p className="mt-10 border-t border-border pt-6 text-sm text-ink-faint">
        Ce document décrit une application en phase de test.{" "}
        <Link href="/" className="text-accent hover:underline">Retour à l&apos;accueil</Link>
      </p>
    </div>
  );
}
