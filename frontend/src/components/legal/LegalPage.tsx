import type { ReactNode } from "react";
import SiteFooter from "@/components/site/SiteFooter";
import SiteHeader from "@/components/site/SiteHeader";

export interface LegalSection {
  title: string;
  body: ReactNode;
}

/** Cadre commun des pages juridiques (conditions, confidentialité). Contenu : voir chaque page. */
export function LegalPage({
  eyebrow,
  title,
  updated,
  intro,
  sections,
}: {
  eyebrow: string;
  title: string;
  updated: string;
  intro: string;
  sections: LegalSection[];
}) {
  return (
    <>
      <SiteHeader variant="solid" />
      <main id="contenu" tabIndex={-1} className="min-h-screen bg-canvas outline-none">
        <article className="mx-auto max-w-3xl px-4 py-12 sm:px-6 sm:py-16">
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-primaryDark">{eyebrow}</p>
          <h1 className="mt-2 font-display text-3xl font-extrabold leading-tight text-ink sm:text-4xl">{title}</h1>
          <p className="mt-2 text-sm text-ash">{updated}</p>
          <p className="mt-6 text-base leading-relaxed text-inkSoft">{intro}</p>
          <div className="mt-10 space-y-8">
            {sections.map((s, i) => (
              <section key={s.title} aria-labelledby={`s${i}`}>
                <h2 id={`s${i}`} className="font-display text-xl font-bold text-ink">
                  {i + 1}. {s.title}
                </h2>
                <div className="mt-2 space-y-3 text-[15px] leading-relaxed text-inkSoft">{s.body}</div>
              </section>
            ))}
          </div>
        </article>
      </main>
      <SiteFooter />
    </>
  );
}
