# Conditions d'utilisation — mentions à valider juridiquement

Page publique : `https://tratra.net/conditions-utilisation` (`frontend/src/app/conditions-utilisation/page.tsx`), version `2026-11-12`.
Les CGU décrivent uniquement les règles appliquées par le code. Rien n'a été inventé : les points ci-dessous sont absents, ou
formulés de façon neutre, en attendant une décision de l'éditeur et la relecture d'un juriste.

## Absent de la page (à fournir)

| Point | Situation actuelle |
|---|---|
| Identité de l'éditeur : dénomination, forme sociale, capital, siège, RCCM, compte contribuable, directeur de la publication, hébergeur | Aucune donnée confirmée dans le projet (`CONTRACT_PDF_LEGAL_MENTIONS` est vide aussi). La page indique que ces mentions « seront publiées ». À renseigner au build web avec `NEXT_PUBLIC_LEGAL_MENTIONS` (valeurs séparées par « \| »), sans modifier le code. |
| Droit applicable et juridiction compétente | Non mentionnés. Le service vise la Côte d'Ivoire (+225, XOF, ARTCI citée dans la politique de confidentialité), mais rien ne le confirme juridiquement. |
| Propriété intellectuelle : licence sur les contenus publiés (photos, annonces, avis, statuts) et sur la marque Tratra | Non rédigée. |
| Délais : traitement des litiges, réponse du support, recours contre une sanction | Aucun délai cité (aucun délai n'est garanti par le code). |

## Formulé de façon neutre (montants ou effets à confirmer)

| Point | Ce que fait le code | Ce que dit la page |
|---|---|---|
| Commission sur les réservations | `PricingRule` réglable au Back-Office ; à défaut, 11 % dans `handy/services/fees.py`. Recouvrement de la commission sur les paiements en espèces : non décidé. | « Précisés dans l'application ou dans l'offre concernée » ; aucun taux. |
| Frais liés aux contrats d'engagement | `commission_percent_*` et `commission_payer` réglables par métier (0 % par défaut). | « Ceux figurant dans l'application pour ce contrat. » |
| Politique d'annulation | `CancellationPolicy` réglable (délai d'annulation gratuite, pourcentage) ; frais sans effet tant que le paiement se fait en espèces. Son affichage avant la réservation n'a pas été vérifié. | Principe seulement, sans délai ni pourcentage. |
| Paiement | Espèces par défaut (`NEXT_PUBLIC_PAYMENT_METHODS=cash`), séquestre désactivé (`NEXT_PUBLIC_ESCROW_ENABLED=false`) : la page s'adapte à ce réglage. | « Tratra n'encaisse pas ce paiement » (mode espèces). |
| Rôle de Tratra et responsabilité | Mise en relation ; la prestation est réalisée par le professionnel. | Responsabilités décrites sans plafond ni clause d'exclusion. La qualification juridique (intermédiaire, non partie au contrat de prestation) reste à valider. |
| Délais Flash, nombre d'annonces « Non vérifié » | Réglables (`DispatchConfig`, `UNVERIFIED_MAX_ACTIVE_SERVICES`). | « Affiché dans l'application » / « indiquée dans votre espace ». |
| Âge minimum | 18 ans (politique de confidentialité, déclaration Google Play). | 18 ans et plus. |
| Nouvelle version des CGU | Les comptes existants ne sont pas bloqués : la nouvelle version leur est proposée (application, Paramètres → Informations légales) et n'est enregistrée qu'après leur acceptation explicite. | Effets d'un refus, préavis et date d'entrée en vigueur non précisés. |
| Modèles de contrat | Déjà marqués « À valider juridiquement ». | Présentés comme une aide à la rédaction. |

## Acceptation enregistrée

- Inscription (site ; application : inscription classique et accompagnée) : case jamais précochée ; le serveur refuse toute inscription sans `accept_terms: true`
  et enregistre la version annoncée (`User.terms_version`) avec la date (`User.terms_accepted_at`), journalisées (`account.terms_accepted`).
- Comptes antérieurs : date d'origine conservée, version vide (« antérieure au versionnage ») : aucune acceptation supposée.
- Application déjà publiée (build 13) : elle n'annonce pas de version → date seule, version vide ; la version en vigueur leur est
  proposée après la mise à jour de l'application.
- Publier une nouvelle version : changer `TERMS_VERSION` et `TERMS_UPDATED_ON` dans `handy/legal.py` et `frontend/src/lib/legal.ts` (un
  test vérifie qu'ils concordent) et `LegalLinks.termsVersion` dans l'application ; un client resté sur l'ancienne version se voit
  refuser l'inscription (`terms_outdated`) et la personne recoche la case après relecture.
