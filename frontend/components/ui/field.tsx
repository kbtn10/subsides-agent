"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export function Label({
  children, htmlFor, optional,
}: { children: React.ReactNode; htmlFor?: string; optional?: boolean }) {
  return (
    <label htmlFor={htmlFor} className="block text-sm font-semibold text-ink mb-1.5">
      {children}
      {optional && <span className="ml-1.5 font-normal text-ink-faint text-xs">(facultatif)</span>}
    </label>
  );
}

const controlBase =
  "w-full rounded-[var(--radius-ctrl)] border border-border bg-surface px-3.5 py-2.5 text-[15px] text-ink " +
  "placeholder:text-ink-faint transition-shadow focus:outline-none focus:border-accent " +
  "focus:ring-4 focus:ring-[var(--accent-ring)]";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(controlBase, className)} {...props} />
  ),
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea ref={ref} className={cn(controlBase, "min-h-[110px] resize-y leading-relaxed", className)} {...props} />
  ),
);
Textarea.displayName = "Textarea";

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select ref={ref} className={cn(controlBase, "appearance-none bg-no-repeat pr-10 cursor-pointer", className)}
      style={{
        backgroundImage:
          "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' fill='none' stroke='%239a938a' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")",
        backgroundPosition: "right 0.75rem center",
      }}
      {...props}>
      {children}
    </select>
  ),
);
Select.displayName = "Select";

// Case à cocher « pilule » (secteurs). Accessible : vrai input caché + label.
export function CheckPill({
  checked, onChange, children,
}: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) {
  return (
    <label
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3.5 py-2 text-sm cursor-pointer select-none transition-colors",
        checked
          ? "border-accent bg-accent-soft text-accent font-medium"
          : "border-border bg-surface text-ink-soft hover:border-border-strong",
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-[var(--accent)]"
      />
      {children}
    </label>
  );
}
