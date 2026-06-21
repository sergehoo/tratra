import { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "accent" }) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 font-semibold transition disabled:opacity-60";
  const styles = {
    primary: "bg-primary text-white hover:bg-primaryDark shadow-soft",
    accent: "bg-accent text-ink hover:brightness-95",
    ghost: "border border-slate-200 text-ink hover:bg-slate-50",
  }[variant];
  return <button className={`${base} ${styles} ${className}`} {...props} />;
}

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`w-full rounded-xl border border-slate-200 px-4 py-2.5 outline-none focus:ring-2 focus:ring-accent ${className}`}
      {...props}
    />
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl border border-slate-100 bg-white p-6 shadow-soft ${className}`}>
      {children}
    </div>
  );
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <Card className="!p-5">
      <p className="text-3xl font-extrabold text-ink">{value}</p>
      <p className="text-sm text-ash">{label}</p>
    </Card>
  );
}

export function Badge({ children, tone = "primary" }: { children: ReactNode; tone?: "primary" | "accent" | "gray" }) {
  const t = {
    primary: "bg-primarySoft text-primaryDark",
    accent: "bg-accentSoft text-ink",
    gray: "bg-slate-100 text-slate-600",
  }[tone];
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${t}`}>{children}</span>;
}
