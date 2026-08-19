"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

type Ton = "succes" | "neutre";
type Toast = { id: number; texte: string; ton: Ton };
const Ctx = createContext<(texte: string, ton?: Ton) => void>(() => {});

/** Toasts légers en bas-centre. Pas de confettis plein écran : un mot soigné
 *  suffit. Auto-disparition douce après 4,5 s. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const pousser = useCallback((texte: string, ton: Ton = "neutre") => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((t) => [...t, { id, texte, ton }]);
  }, []);
  return (
    <Ctx.Provider value={pousser}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-24 z-[60] flex flex-col items-center gap-2 px-4 lg:bottom-8">
        {toasts.map((t) => <ToastItem key={t.id} toast={t}
          onDone={() => setToasts((l) => l.filter((x) => x.id !== t.id))} />)}
      </div>
    </Ctx.Provider>
  );
}

function ToastItem({ toast, onDone }: { toast: Toast; onDone: () => void }) {
  const [sortie, setSortie] = useState(false);
  useEffect(() => {
    const t1 = setTimeout(() => setSortie(true), 4000);
    const t2 = setTimeout(onDone, 4500);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [onDone]);
  const style = toast.ton === "succes"
    ? "bg-accent text-white" : "bg-ink text-white";
  return (
    <div className={`pointer-events-auto max-w-sm rounded-[var(--radius-card)] px-4 py-3 text-sm shadow-[var(--shadow-lift)] transition-all duration-500 ${style} ${
      sortie ? "translate-y-2 opacity-0" : "translate-y-0 opacity-100"}`}>
      {toast.texte}
    </div>
  );
}

export function useToast() { return useContext(Ctx); }
