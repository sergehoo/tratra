# Adresses et frais de déplacement

## Adresses (compte unique)
- `GET/POST /handy/me/addresses/`, `GET/PATCH/DELETE /handy/me/addresses/<id>/`, `POST …/primary/` : une adresse principale (au plus), des secondaires, des favorites (10 max) ; visibles de leur seul propriétaire. L'adresse principale reflète les champs historiques du compte.
- `GET /handy/geo/search/?q=` (autocomplétion/géocodage) et `GET /handy/geo/reverse/?lat&lng&consent=true` : fournisseur `GEO_PROVIDER` (nominatim, google ou none), cache `GEO_CACHE_TTL`, limite `GEO_MAX_CALLS_PER_MINUTE` + throttle `THROTTLE_GEO`. Panne ou quota => 503 `manual_entry: true` : l'application bascule sur la saisie manuelle. Le cache ne contient jamais de coordonnées exactes.
- La position de l'appareil exige un consentement explicite (`location_consent`), lecture unique, aucun suivi. L'adresse n'est pas demandée à l'inscription mais avant la première demande ou prestation (`address_complete` dans `/me/dashboard/`).

## Transport
- Back-Office > Administration > Réglages > Transport (droit `settings.manage`) : activation (désactivé par défaut), seuil (1 km), devise, mode de calcul, forfait de secours (1 000 FCFA), arrondi, date d'application, tranches horaires (jours, heures d'Abidjan, tarif/km, zone, validité), zones. Chaque changement exige un motif, crée une version (instantané) et une trace d'audit. Aucune suppression : on désactive.
- Modes : `round_trip_billed` (km d'aller × 2 × tarif) ou `round_trip_included` (km d'aller × tarif, retour inclus). Le retour n'est jamais facturé deux fois.
- Calcul serveur (`transport/pricing.py`) : distance routière via `ROUTING_OSRM_URL` (jamais une estimation à vol d'oiseau) ; sous le seuil = 0 ; sinon tranche applicable ; sans tarif applicable ou sans distance => forfait de secours, signalé (`fallback_reason`). Prestation sans déplacement (`Service.requires_travel=false`) : 0.
- `POST /handy/transport/quote/` : devis + créneaux (maintenant, demain matin, heures creuses, pointe) réellement calculés ; l'adresse du prestataire n'apparaît jamais.
- À la réservation, le serveur recalcule et fige `Booking.transport_fee` + `transport_quote` (tarif, distance, créneau, version). Un `expected_transport_fee` différent => 409 `transport_changed` (rien n'est créé). Le paiement ajoute ce montant UNE fois, recalculé depuis ses sources. `POST /handy/bookings/<id>/transport/` recalcule explicitement (accord `accept_fee`), tant qu'aucun paiement n'existe.
- Missions longue durée : aucun transport automatique (les occurrences de contrat ne passent pas par ce calcul).
