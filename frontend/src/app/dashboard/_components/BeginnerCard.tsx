"use client";
import { CheckCircle2, Circle, Hourglass } from "lucide-react";
import { ButtonLink, Card, cx } from "@/components/ds";
import { nextActionHref, type OnbState } from "@/lib/onboarding";
import { useData } from "@/lib/useData";

/**
 * Tableau de bord débutant : inscription professionnelle commencée (accompagnée) et pas encore publiée → étapes faites et restantes,
 * prochaine action calculée par le serveur, UN seul bouton « Continuer ». Rien pour un compte qui n'a pas commencé ce parcours.
 */
export function BeginnerCard() {
  const { data } = useData<OnbState>("/me/onboarding/");
  if (!data || !data.trade || data.published) return null;
  const waiting = data.next_action.code === "wait";
  return (
    <Card aria-labelledby="beginner-title">
      <div className="flex items-baseline gap-3">
        <h2 id="beginner-title" className="flex-1 font-display text-lg font-extrabold text-ink">Mon inscription professionnelle</h2>
        <span className="font-display text-lg font-extrabold text-primaryDark">
          {data.done}/{data.total}
        </span>
      </div>
      <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-lineSoft" role="progressbar" aria-valuemin={0} aria-valuemax={data.total} aria-valuenow={data.done} aria-label="Progression de l’inscription">
        <div className="h-full rounded-full bg-primary" style={{ width: `${data.total ? (data.done / data.total) * 100 : 0}%` }} />
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {data.steps.map((s) => (
          <li key={s.key} className={cx("flex items-center gap-1.5 text-xs", s.state === "todo" ? "text-ash" : "text-inkSoft")}>
            {s.state === "done" ? (
              <CheckCircle2 aria-hidden className="h-4 w-4 text-success" />
            ) : s.state === "waiting" ? (
              <Hourglass aria-hidden className="h-4 w-4 text-accentDark" />
            ) : (
              <Circle aria-hidden className="h-4 w-4 text-fog" />
            )}
            <span>
              {s.label}
              <span className="sr-only"> : {s.state === "done" ? "fait" : s.state === "waiting" ? "en cours de vérification" : "à faire"}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-sm font-semibold text-ink">
        {waiting ? "L’équipe Tratra vérifie votre dossier. Vous serez prévenu(e) par notification." : `Prochaine étape : ${data.next_action.label}`}
      </p>
      <ButtonLink href={nextActionHref(data.next_action)} size="lg" block className="mt-4 sm:w-auto">
        {waiting ? "Voir mon dossier" : "Continuer"}
      </ButtonLink>
    </Card>
  );
}
