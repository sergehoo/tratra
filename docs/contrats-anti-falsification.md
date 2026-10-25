# Contrats : modèles juridiques, signatures et anti-falsification

Module `engagements` (contrats mensuels, récurrents ou de longue durée). Ce document décrit ce qui est garanti techniquement, ce qui
reste à la charge d'une revue juridique humaine, et l'exploitation (clés, migrations, déploiement).

## 1. Ce que Tratra NE fait PAS

- Tratra ne déclare **aucun** modèle « conforme ». Un modèle a quatre statuts : `Brouillon`, `À valider juridiquement`,
  `Validé par revue juridique` (nom du réviseur et note obligatoires, droit `contracts.legal_review`), `Retiré`.
- Les deux modèles livrés (`emploi-domestique-salarie`, `prestation-independante`) sont **« À valider juridiquement »**. Ils contiennent
  des passages `[À compléter par la revue juridique]` ; la validation est refusée tant qu'il en reste un.
- Les références légales citées (Code du travail, loi n° 2015-532 ; protection des données, loi n° 2013-450 ; OHADA/AUDCG limité à
  son champ) portent la mention « à confirmer » : elles doivent être vérifiées par la revue juridique avant validation.
- Tant qu'aucun modèle n'est validé pour une relation (salarié / indépendant) et un métier, les contrats suivent le parcours existant
  (acceptation des conditions, sans document scellé) : rien n'est présenté comme un contrat juridiquement relu.

## 2. Salarié ≠ prestation indépendante

`work_relationship` du contrat choisit le modèle : `employment` → modèle salarié (employeur / salarié, Code du travail),
`independent` → modèle de prestation (client / prestataire). Un modèle d'une relation ne peut jamais servir l'autre
(`template_mismatch`). Les articles sont figés dans le contrat au moment de la proposition, puis à chaque avenant.

## 3. Trois notions distinctes

| Notion | Ce que c'est | Où |
| --- | --- | --- |
| Acceptation | Chaque partie accepte les conditions (version des termes) | `ContractAcceptance` |
| Signature des parties | Signature électronique **simple** : compte, date, heure, empreinte du document exact signé, IP hachée | `ContractSignature` (une par rôle et par document) |
| Scellement Tratra | Signature numérique **Ed25519** de la plateforme sur l'empreinte du PDF | `ContractDocument.signature` |

Parcours avec modèle validé : `Proposé → Accepté` (document « à signer » scellé) `→ Signé` (deux signatures, contrat final scellé)
`→ Actif` à la date de début. La signature porte sur l'empreinte du document à signer ; une seconde signature du même rôle est refusée,
deux signatures simultanées n'émettent qu'un seul contrat final (verrou + contrainte d'unicité).

## 4. Document scellé

- Référence `TRT-CTR-AAAA-NNNNNN` (compteur annuel sous verrou, unique même en concurrence) ; avenants `…-AV1`, `…-AV2`.
- PDF déterministe ; l'empreinte SHA-256 est calculée sur **les octets du PDF final** (QR inclus), puis scellée.
- Charge utile scellée (JSON canonique, clés triées, sans espaces) :
  `reference, kind, stage, version, sha256, terms_hash, issued_at`.
- QR et URL imprimée : `<PUBLIC_WEB_URL>/verify/contract/<jeton>`. Jeton aléatoire de 256 bits, seule son empreinte est en base.
- Immuabilité en base (déclencheurs PostgreSQL, migration `engagements.0004`) : aucun document, signature ou événement ne peut être
  supprimé ; sur un document seuls les champs de révocation peuvent être renseignés, une seule fois.
- Un avenant produit un **nouveau** document ; l'original n'est jamais modifié.
- Téléchargement réservé aux deux parties ; l'empreinte du fichier conservé est revérifiée à chaque téléchargement (409 sinon).

## 5. Vérification publique (sans données personnelles)

- `GET /handy/public/contracts/verify/<jeton>/` et page `/verify/contract/<jeton>`.
- `POST /handy/public/contracts/verify-file/` (PDF ≤ 15 Mo) : retrouve le document par son empreinte exacte. Un seul octet
  modifié → « aucun document Tratra ne correspond ».
- `GET /handy/public/contracts/keys/` : clés publiques pour une vérification indépendante.
- États : `authentic`, `superseded` (version à signer remplacée par le contrat signé), `revoked`, `altered` (fichier conservé
  altéré), `invalid_signature`, `key_revoked`. La réponse ne contient ni nom, ni montant, ni adresse : référence, état, dates,
  empreinte, scellement, « signé par les deux parties » (sans identité), avenants.
- Limitation : `THROTTLE_VERIFY` (60/min par défaut).

Vérification indépendante (Python) :

```python
import base64, json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
r = ...  # réponse JSON de la vérification
pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(<clé publique du kid>))
msg = json.dumps(r["seal"]["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
pub.verify(base64.b64decode(r["seal"]["signature"]), msg)  # lève une exception si invalide
```

## 6. Clés de scellement

- Clé privée Ed25519 générée côté serveur, chiffrée (Fernet) avec `CONTRACT_SIGNING_KEK` (à défaut une dérivée de `SECRET_KEY`),
  jamais affichée ni exportée. Une seule clé active (contrainte).
- `python manage.py contract_keys list | rotate | revoke <kid> --reason "…"` ; même chose au Back-Office (droit `contracts.keys`,
  Super Admin). Rotation : l'ancienne clé reste valable pour ses documents. Révocation (compromission) : ses documents sont signalés
  `key_revoked`, une nouvelle clé devient active.
- **Changer `CONTRACT_SIGNING_KEK` rend illisible la clé privée active** (le scellement échoue) ; les documents déjà émis restent
  vérifiables (seule la clé publique sert). Après tout changement de KEK, lancer immédiatement `contract_keys rotate` : la nouvelle clé
  est chiffrée avec la nouvelle KEK, l'ancienne passe « retirée ». Le plus simple : définir la KEK **avant le premier contrat scellé**.

## 7. Droits Back-Office

| Droit | Rôles | Usage |
| --- | --- | --- |
| `contracts.templates` | ops, legal, super admin | rédiger, soumettre, retirer, nouvelle version |
| `contracts.legal_review` | legal, super admin | valider un modèle (revue juridique faite) |
| `contracts.revoke` | ops, super admin | révoquer un document (motif ≥ 10 caractères) |
| `contracts.keys` | super admin | rotation / révocation des clés |

Toutes ces actions sont journalisées (`trust.audit`).

## 8. Déploiement

1. Définir `CONTRACT_SIGNING_KEK` (valeur aléatoire longue, gardée dans le coffre des secrets) **avant** le premier contrat scellé.
2. Migrations : `handy.0062_contract_modes`, `engagements.0003_contract_modes`, `engagements.0004_immutable_documents_and_templates`
   (ajouts de colonnes nullables / avec défaut, fonctions et déclencheurs PostgreSQL, deux modèles « À valider juridiquement »).
   Aucune donnée existante modifiée ; les prestations existantes restent « ponctuelles ».
3. Faire relire et compléter les modèles par un juriste, puis les valider au Back-Office (rôle « legal »).
4. La première clé est créée automatiquement au premier scellement ; `contract_keys list` pour la contrôler.

## 9. Présentation du PDF (modèle A4 institutionnel, 25 oct. 2026)

Moteur `engagements/pdf.py` (sans dépendance, Helvetica standard, rendu DÉTERMINISTE) et composition `engagements/contract_pdf.py`, pour les contrats
salariés et indépendants et pour les avenants :

- **en-tête de chaque page** : logo officiel (`static/img/tratra_logo.webp`), TRATRA, nature du document, référence, version, date d'émission, étape ;
- **page d'identification** : titre selon la nature juridique (« Contrat de travail » / « Contrat de prestation de services »), QR code, modèle et
  statut de sa revue juridique, deux encadrés des parties (nom, prénom(s), Tratra ID, téléphone, adresse, qualité, profession, vérification ;
  entreprise, RCCM, siège si le donneur d'ordre est une organisation) — **aucune pièce KYC** n'est reproduite ;
- **synthèse contractuelle** : métier, intitulé, missions, lieu, durée, horaires, rémunération, échéances, préavis, avantages, conditions particulières
  (une ligne de tableau n'est jamais coupée entre deux pages) ;
- **articles** : texte EXACT des articles figés du modèle validé (titres numérotés, paragraphes espacés, continuation sur les pages suivantes, jamais
  tronqués) ; seules les ponctuations doublées (« .. », « ,, ») et les espaces multiples sont corrigés à l'affichage ;
- **signatures** : deux blocs (signataire, qualité, consentement, date et heure, preuve `SIG-nnnnnn`, empreinte du document signé) ;
- **sécurité** : QR code, référence unique, version, horodatage, clé Ed25519 qui scelle (`signing.sign(..., key=)` : même clé que celle imprimée),
  empreintes des conditions et du document signé, adresse de vérification complète. L'empreinte SHA-256 du fichier lui-même et sa signature Ed25519
  sont calculées après le rendu, comme avant : **mécanisme cryptographique inchangé** ;
- **pied de page de chaque page** : TRATRA + référence + version, « Page X/Y », mention de vérification, et mentions légales de
  `CONTRACT_PDF_LEGAL_MENTIONS` (séparées par « | » ; vide = aucune mention, rien n'est inventé).

Les documents déjà scellés ne sont jamais régénérés : seuls les nouveaux documents utilisent ce modèle (un contrat dont la version à signer a été émise
avec l'ancien rendu reçoit un exemplaire final au nouveau format, qui cite l'empreinte du document réellement signé).

**Cohérence métier / missions** (`engagements/services/quality.py`) : avant la proposition, l'auteur voit un avertissement si les missions sont vides
ou sans rapport avec le vocabulaire du métier (noms et synonymes du catalogue) — jamais un blocage ni une réécriture.

**Contrôle visuel** : `pdftoppm` de ce poste remplace Helvetica-Bold par la version normale (substitution système) ; le contrôle se fait avec PDFKit
(rendu Quartz), qui affiche fidèlement les polices standard.

