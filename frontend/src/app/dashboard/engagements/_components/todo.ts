import type { TodoItem } from "@/lib/engagements";

/** Lien de chaque tâche « à faire » : la page et l'onglet où l'on agit. */
export function todoHref(t: TodoItem): string {
  const c = t.contract_id;
  switch (t.kind) {
    case "accept_contract":
    case "answer_amendment":
      return `/dashboard/engagements/contracts/${c}`;
    case "confirm_payment":
    case "answer_adjustment":
    case "pay_installment":
    case "late_installment":
      return `/dashboard/engagements/contracts/${c}?tab=pay`;
    case "validate_event":
    case "confirm_attendance":
      return `/dashboard/engagements/contracts/${c}?tab=planning`;
    case "answer_replacement":
      return "/dashboard/engagements/replacements";
    case "review_applications":
    case "answer_interview":
      return t.posting_id ? `/dashboard/engagements/postings/${t.posting_id}` : "/dashboard/engagements";
    default:
      return c ? `/dashboard/engagements/contracts/${c}` : "/dashboard/engagements";
  }
}

