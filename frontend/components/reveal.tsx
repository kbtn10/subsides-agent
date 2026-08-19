"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";

/**
 * Apparition au défilement — avec filet de sécurité.
 *
 * `whileInView` seul a un défaut rédhibitoire : si l'IntersectionObserver ne
 * se déclenche pas (défilement instantané, restauration de position, section
 * déjà passée), le contenu reste à opacity 0 — donc invisible pour de bon.
 * On observe nous-mêmes, et on révèle de toute façon après un court délai.
 * L'animation est un bonus, jamais une condition d'affichage.
 */
export function Reveal({
  children, delay = 0, className,
}: { children: React.ReactNode; delay?: number; className?: string }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setVisible(true); obs.disconnect(); } },
      { rootMargin: "0px 0px -10% 0px" },
    );
    obs.observe(el);
    // Filet : quoi qu'il arrive, le contenu est lisible.
    const t = setTimeout(() => setVisible(true), 1500);
    return () => { obs.disconnect(); clearTimeout(t); };
  }, []);

  return (
    <motion.div
      ref={ref}
      className={className}
      initial={reduce ? false : { opacity: 0, y: 16 }}
      animate={visible || reduce ? { opacity: 1, y: 0 } : undefined}
      transition={{ duration: 0.5, ease: "easeOut", delay: reduce ? 0 : delay }}
    >
      {children}
    </motion.div>
  );
}
