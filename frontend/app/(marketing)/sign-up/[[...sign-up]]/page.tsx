import { SignUp } from "@clerk/nextjs";
import { PRODUCT_NAME } from "@/lib/constants";

export default function SignUpPage() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center gap-6 py-8">
      <div className="text-center">
        <h1 className="font-display text-2xl font-semibold text-ink">
          Rejoignez {PRODUCT_NAME}
        </h1>
        <p className="mt-1 text-ink-soft">
          On analyse les subsides pour vous — décrivez votre ASBL une fois.
        </p>
      </div>
      <SignUp />
    </div>
  );
}
