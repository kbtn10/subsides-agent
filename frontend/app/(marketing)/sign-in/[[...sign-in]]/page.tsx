import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center gap-6 py-8">
      <div className="text-center">
        <h1 className="font-display text-2xl font-semibold text-ink">Bon retour</h1>
        <p className="mt-1 text-ink-soft">Reconnectez-vous pour retrouver vos subsides.</p>
      </div>
      <SignIn />
    </div>
  );
}
