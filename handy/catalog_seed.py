"""Référentiel des métiers (Côte d'Ivoire) — familles, métiers, prestations et synonymes de recherche, appliqué de façon IDEMPOTENTE.

  FAMILLE    regroupement de navigation (`CatalogFamily`)                « Informatique & Numérique »
  MÉTIER     catégorie racine (`ServiceCategory`, parent vide)            « Maintenance informatique »  (= sous-catégorie)
  PRESTATION sous-catégorie du métier                                     « Récupération de données »

Règles d'application (migration `handy.0064` et commande `manage.py sync_catalog`) :
  - rien n'est supprimé, renommé, déplacé ni masqué : un métier qui existe déjà (même slug, slug historique listé dans `aliases`, ou même
    nom sans accents ni casse) est RÉUTILISÉ tel quel — on y ajoute seulement les prestations manquantes, sa famille si elle est vide, son
    icône si elle est vide et les synonymes manquants ;
  - une prestation existe déjà si son métier a une prestation au même nom (sans accents ni casse) : jamais de doublon ;
  - ré-appliquer ne change rien (les identifiants ne changent jamais ; les réglages de l'administration — visibilité, ordre, mise en avant,
    noms — sont conservés).

Les données ci-dessous sont VERSIONNÉES : pour les faire évoluer, ajouter une nouvelle migration plutôt que réécrire l'historique."""
import unicodedata
from collections import Counter
from typing import Dict, List, NamedTuple, Sequence, Tuple

from django.utils.text import slugify

VERSION = "ci-2026-10"


class Family(NamedTuple):
    slug: str
    name: str
    icon: str
    position: int
    description: str
    keywords: str


class Trade(NamedTuple):
    family: str
    slug: str
    name: str
    icon: str
    keywords: str
    prestations: Sequence[Tuple[str, str]]
    aliases: Sequence[str] = ()


FAMILIES: Sequence[Family] = (
    Family("informatique-numerique", "Informatique & Numérique", "fa-solid fa-laptop", 10,
           "Dépannage informatique, réseaux, sites et applications, sécurité, formation.", "informatique, numérique, digital, tech, ordinateur, pc"),
    Family("telephones-electronique", "Téléphones & électronique", "fa-solid fa-mobile-screen-button", 20,
           "Téléphones, tablettes, télévisions, audiovisuel et électronique.", "téléphone, portable, électronique, télé, réparateur"),
    Family("electromenager-froid", "Électroménager & froid", "fa-solid fa-snowflake", 30,
           "Réfrigérateurs, machines à laver, cuisinières, climatisation et froid.", "électroménager, froid, frigoriste, clim, frigo"),
    Family("auto-moto-velo", "Auto, moto & vélo", "fa-solid fa-car-side", 40,
           "Mécanique, dépannage et remorquage, motos, scooters et vélos.", "voiture, véhicule, garage, mécanicien, moto"),
    Family("electricite-plomberie", "Électricité & plomberie", "fa-solid fa-bolt", 50,
           "Pannes de courant, installations électriques, fuites, sanitaires, pompes.", "électricien, plombier, courant, eau"),
    Family("batiment-travaux", "Bâtiment & rénovation", "fa-solid fa-helmet-safety", 60,
           "Construction, rénovation, maçonnerie, peinture, carrelage, toiture.", "btp, chantier, travaux, maçon, construction"),
    Family("bois-metal-serrurerie", "Menuiserie, métallerie & serrurerie", "fa-solid fa-hammer", 70,
           "Meubles et menuiserie, soudure, portails, grilles, serrures.", "menuisier, soudeur, ferronnier, serrurier"),
    Family("entretien-jardin", "Nettoyage, entretien & jardin", "fa-solid fa-broom", 80,
           "Ménage, nettoyage, désinsectisation, jardinage et espaces verts.", "nettoyage, ménage, jardin, propreté"),
    Family("couture-cordonnerie", "Couture, cordonnerie & tapisserie", "fa-solid fa-scissors", 90,
           "Couture et retouches, réparation de chaussures, tapisserie.", "couturier, tailleur, cordonnier, tapissier"),
    Family("transport-demenagement", "Transport & déménagement", "fa-solid fa-truck", 100,
           "Déménagement, transport de marchandises, livraison.", "transport, camion, livraison, déménageur"),
    Family("equipements-professionnels", "Équipements professionnels", "fa-solid fa-industry", 110,
           "Maintenance des machines et équipements des entreprises et commerces.", "entreprise, machine, équipement, maintenance"),
)

TRADES: Sequence[Trade] = (
    # ── Informatique & Numérique ─────────────────────────────────────────────────────────────────────────────────────
    Trade("informatique-numerique", "maintenance-informatique", "Maintenance informatique", "fa-solid fa-computer",
          "ordinateur, pc, laptop, portable, informaticien, dépannage informatique, réparation ordinateur", (
              ("Diagnostic et réparation d'ordinateur", "pc ne démarre pas, ordinateur ne s'allume pas, écran noir, pc lent, ordinateur lent, plante, bug"),
              ("Remplacement d'écran de PC portable", "écran cassé, dalle, écran fissuré, écran laptop"),
              ("Remplacement de clavier, batterie ou chargeur", "clavier, batterie pc, chargeur pc, ne charge pas"),
              ("Installation de Windows, macOS ou Linux", "formatage, formater, réinstaller windows, système d'exploitation, os"),
              ("Suppression de virus et nettoyage logiciel", "virus, antivirus, malware, publicités, logiciel malveillant"),
              ("Récupération de données", "fichiers perdus, disque dur, clé usb, données effacées, récupérer photos"),
              ("Ajout de SSD et de mémoire RAM", "ssd, ram, mémoire, accélérer pc, disque dur"),
              ("Nettoyage et pâte thermique", "surchauffe, ordinateur chauffe, ventilateur bruyant, poussière"),
          ), aliases=("reparation-ordinateur",)),
    Trade("informatique-numerique", "reseaux-wifi", "Réseaux & Wi-Fi", "fa-solid fa-wifi",
          "réseau, wifi, wi-fi, internet, connexion, box, routeur, câblage", (
              ("Installation et configuration de box ou routeur", "box internet, routeur, modem, fibre, orange, mtn, moov, configuration wifi"),
              ("Extension de couverture Wi-Fi", "répéteur, wifi faible, pas de signal, point d'accès, mesh"),
              ("Câblage réseau RJ45", "câble réseau, rj45, ethernet, baie de brassage, prise réseau"),
              ("Dépannage de connexion internet", "pas d'internet, connexion lente, wifi ne marche pas, coupure internet"),
              ("Réseau d'entreprise et partage de fichiers", "lan, switch, serveur de fichiers, réseau bureau, partage imprimante"),
              ("Sécurisation du Wi-Fi", "mot de passe wifi, contrôle parental, wifi piraté"),
          )),
    Trade("informatique-numerique", "developpement-web-mobile", "Développement web & mobile", "fa-solid fa-laptop-code",
          "site internet, site web, application, appli, développeur, programmation", (
              ("Création de site vitrine", "site internet, page web, wordpress, site entreprise"),
              ("Boutique en ligne", "e-commerce, vente en ligne, boutique, paiement mobile money"),
              ("Application mobile Android et iOS", "appli, application, android, iphone, flutter"),
              ("Logiciel de gestion sur mesure", "logiciel de gestion, stock, facturation, erp"),
              ("Maintenance et mise à jour de site", "site en panne, site piraté, mise à jour wordpress, bug site"),
              ("Nom de domaine, hébergement et e-mails professionnels", "domaine, hébergement, email professionnel, .ci"),
          )),
    Trade("informatique-numerique", "cybersecurite", "Cybersécurité", "fa-solid fa-user-shield",
          "sécurité informatique, piratage, hacker, protection des données", (
              ("Audit de sécurité informatique", "audit, failles, vulnérabilités, test d'intrusion"),
              ("Récupération de compte piraté", "compte piraté, facebook piraté, whatsapp piraté, email piraté, hacké"),
              ("Installation d'antivirus et de pare-feu", "antivirus, pare-feu, firewall"),
              ("Sauvegarde et protection des données", "sauvegarde, backup, rançongiciel, ransomware"),
              ("Sensibilisation des équipes aux arnaques en ligne", "formation sécurité, phishing, hameçonnage, arnaque en ligne, brouteur"),
          )),
    Trade("informatique-numerique", "videosurveillance", "Vidéosurveillance & sécurité", "fa-solid fa-video",
          "caméra, cctv, vidéosurveillance, surveillance, alarme", (
              ("Installation de caméras de surveillance", "caméra, cctv, caméra ip, dvr, nvr, hikvision"),
              ("Visionnage des caméras sur téléphone", "voir caméra sur téléphone, accès à distance, application caméra"),
              ("Dépannage de vidéosurveillance", "caméra ne marche pas, pas d'image, enregistreur en panne, dvr en panne"),
              ("Alarme anti-intrusion", "alarme, détecteur de mouvement, sirène, antivol"),
              ("Interphone et visiophone", "interphone, visiophone, sonnette vidéo"),
              ("Contrôle d'accès par badge ou empreinte", "badge, pointeuse, empreinte digitale, biométrique, contrôle d'accès"),
          )),
    Trade("informatique-numerique", "telephonie", "Téléphonie d'entreprise", "fa-solid fa-phone",
          "standard téléphonique, pabx, téléphone fixe, voip", (
              ("Installation de standard téléphonique", "pabx, ipbx, standard, autocom"),
              ("Téléphonie sur IP", "voip, téléphone ip, sip"),
              ("Câblage et postes téléphoniques", "ligne téléphonique, poste fixe, câblage téléphone"),
              ("Dépannage de ligne ou de standard", "pas de tonalité, standard en panne, téléphone fixe ne marche pas"),
          )),
    Trade("informatique-numerique", "bureautique", "Bureautique & imprimantes", "fa-solid fa-print",
          "imprimante, photocopieur, office, word, excel, scanner, bureautique", (
              ("Installation et dépannage d'imprimante", "imprimante ne marche pas, bourrage papier, imprimante hp, canon, epson, pilote"),
              ("Entretien de photocopieur", "photocopieuse, copieur, toner, cartouche"),
              ("Installation de Microsoft Office et de logiciels", "word, excel, office, logiciel, licence"),
              ("Saisie et mise en page de documents", "saisie, mise en page, cv, rapport, mémoire"),
              ("Configuration de messagerie", "email, outlook, gmail, boîte mail"),
          )),
    Trade("informatique-numerique", "cloud-serveurs", "Cloud & serveurs", "fa-solid fa-cloud",
          "serveur, cloud, hébergement, sauvegarde en ligne, microsoft 365, google workspace", (
              ("Installation et maintenance de serveur", "serveur, windows server, linux, nas"),
              ("Migration vers le cloud", "cloud, google drive, onedrive, microsoft 365, google workspace"),
              ("Sauvegarde automatique en ligne", "backup cloud, sauvegarde, synchronisation"),
              ("Virtualisation", "vmware, proxmox, machine virtuelle"),
              ("Administration et supervision système", "infogérance, monitoring, administrateur système"),
          )),
    Trade("informatique-numerique", "design-numerique", "Design numérique", "fa-solid fa-palette",
          "graphiste, design, logo, infographie, affiche", (
              ("Logo et identité visuelle", "logo, charte graphique, identité visuelle"),
              ("Affiches, flyers et cartes de visite", "flyer, affiche, carte de visite, kakemono, banderole"),
              ("Visuels pour réseaux sociaux", "visuels facebook, instagram, post, bannière"),
              ("Montage vidéo", "montage vidéo, clip, vidéo de mariage"),
              ("Maquettes de sites et d'applications", "ui, ux, maquette, figma"),
          )),
    Trade("informatique-numerique", "marketing-digital", "Marketing digital", "fa-solid fa-bullhorn",
          "réseaux sociaux, community manager, publicité facebook, référencement", (
              ("Gestion de pages sur les réseaux sociaux", "community manager, facebook, instagram, tiktok, page entreprise"),
              ("Publicité en ligne", "sponsoriser, booster, publicité facebook, google ads"),
              ("Référencement de site", "seo, référencement, être visible sur google"),
              ("Fiche Google Maps de l'entreprise", "google maps, google my business, fiche établissement"),
              ("Campagnes SMS et WhatsApp", "sms, whatsapp business, mailing, newsletter"),
          )),
    Trade("informatique-numerique", "formation-informatique", "Formation informatique", "fa-solid fa-chalkboard-user",
          "cours informatique, formation, apprendre l'ordinateur", (
              ("Initiation à l'ordinateur et à internet", "débutant, apprendre ordinateur, internet, initiation"),
              ("Formation Word, Excel et PowerPoint", "excel, word, powerpoint, bureautique"),
              ("Formation au développement web", "programmation, coder, html, javascript"),
              ("Formation en infographie", "photoshop, illustrator, canva, graphisme"),
              ("Cours d'informatique à domicile", "répétiteur informatique, cours à domicile"),
          )),
    Trade("informatique-numerique", "domotique", "Domotique & maison connectée", "fa-solid fa-house-signal",
          "domotique, maison connectée, maison intelligente, automatisme", (
              ("Éclairage et prises connectés", "ampoule connectée, prise connectée, alexa, google home"),
              ("Motorisation de portail et de volets", "portail automatique, motorisation portail, télécommande portail, volet roulant"),
              ("Serrure connectée", "serrure électronique, serrure à code, serrure intelligente"),
              ("Scénarios et automatismes", "automatisation, scénario, minuterie, home assistant"),
              ("Pilotage de la climatisation à distance", "clim connectée, thermostat connecté, wifi clim"),
          )),
    # ── Téléphones & électronique ────────────────────────────────────────────────────────────────────────────────────
    Trade("telephones-electronique", "telephones-tablettes", "Téléphones & tablettes", "fa-solid fa-mobile-screen-button",
          "téléphone, smartphone, portable, tablette, iphone, samsung, tecno, itel, infinix, réparateur téléphone", (
              ("Remplacement d'écran", "écran cassé, vitre cassée, écran fissuré, écran noir, tactile ne marche pas, afficheur"),
              ("Remplacement de batterie", "batterie, se décharge vite, batterie gonflée, ne tient pas la charge"),
              ("Réparation du connecteur de charge", "ne charge pas, port de charge, prise de charge, chargeur"),
              ("Téléphone tombé dans l'eau", "mouillé, eau, oxydation, tombé dans l'eau"),
              ("Haut-parleur, micro et caméra", "pas de son, micro, on ne m'entend pas, caméra floue, écouteur"),
              ("Flashage et mise à jour du logiciel", "flasher, bloqué sur le logo, redémarre tout seul, mise à jour"),
              ("Récupération des données du téléphone", "photos perdues, contacts, whatsapp, sauvegarde"),
              ("Réparation de tablette", "tablette, ipad, galaxy tab"),
          ), aliases=("reparation-smartphone", "reparation-telephone")),
    Trade("telephones-electronique", "tv-audiovisuel-electronique", "TV, audiovisuel & électronique", "fa-solid fa-tv",
          "télé, télévision, tv, radio, électronicien, réparateur tv, audiovisuel", (
              ("Réparation de téléviseur", "télé ne s'allume plus, pas d'image, écran noir, son sans image, lignes sur l'écran, tv led, smart tv"),
              ("Installation d'antenne et de parabole", "parabole, antenne, canal+, startimes, tnt, pas de signal"),
              ("Installation et réglage de décodeur", "décodeur, canal plus, startimes, chaînes"),
              ("Fixation murale de téléviseur", "support mural, accrocher la télé, fixer tv"),
              ("Réparation de radio et de chaîne hi-fi", "radio, poste radio, chaîne hifi, lecteur dvd"),
              ("Sonorisation et home cinéma", "sono, baffle, ampli, enceinte, home cinéma, barre de son"),
              ("Réparation de cartes électroniques", "carte électronique, alimentation, carte mère"),
              ("Onduleur et régulateur de tension", "onduleur, stabilisateur, régulateur de tension, coupures de courant"),
          )),
    # ── Électroménager & froid ───────────────────────────────────────────────────────────────────────────────────────
    Trade("electromenager-froid", "electromenager", "Électroménager", "fa-solid fa-blender",
          "électroménager, appareil ménager, réparateur électroménager", (
              ("Réparation de réfrigérateur et congélateur", "frigo, réfrigérateur, congélateur, ne refroidit plus, ne fait plus de glace, frigo coule, recharge gaz frigo"),
              ("Réparation de machine à laver", "machine à laver, lave-linge, ne vidange pas, ne tourne pas, machine fuit"),
              ("Réparation de cuisinière et de four", "cuisinière, four, gazinière, plaque, brûleur, four à gaz"),
              ("Réparation de micro-ondes", "micro-ondes, ne chauffe plus"),
              ("Réparation de ventilateur", "ventilateur, brasseur, ne tourne plus"),
              ("Réparation de petit électroménager", "fer à repasser, blender, mixeur, bouilloire, cafetière"),
              ("Réparation de chauffe-eau électrique", "chauffe-eau, ballon d'eau chaude, pas d'eau chaude"),
              ("Réparation de fontaine à eau", "fontaine, distributeur d'eau"),
          ), aliases=("reparation-electromenager",)),
    Trade("electromenager-froid", "climatisation", "Climatisation & froid", "fa-solid fa-snowflake",
          "clim, climatiseur, split, frigoriste, climatisation", (
              ("Installation de climatiseur split", "pose clim, installer clim, split, inverter"),
              ("Entretien et nettoyage de climatiseur", "nettoyage clim, entretien clim, clim sale, filtre"),
              ("Recharge de gaz", "recharge gaz, clim ne refroidit plus, clim souffle chaud, gaz r410, r22"),
              ("Dépannage de climatiseur", "clim ne démarre pas, clim coule, fuite d'eau clim, clim fait du bruit, télécommande clim"),
              ("Déplacement de climatiseur", "démonter clim, déplacer clim, désinstaller clim"),
              ("Climatisation centrale et cassette", "clim centrale, gainable, cassette, armoire"),
              ("Chambre froide et vitrine réfrigérée", "chambre froide, froid commercial, vitrine réfrigérée"),
          ), aliases=("climatisation-froid",)),
    # ── Auto, moto & vélo ────────────────────────────────────────────────────────────────────────────────────────────
    Trade("auto-moto-velo", "mecanique-auto", "Mécanique automobile", "fa-solid fa-car-side",
          "mécanicien, garage, voiture, auto, véhicule, mécanique", (
              ("Diagnostic électronique", "voyant moteur, valise diagnostic, check engine, scanner auto"),
              ("Vidange et entretien", "vidange, huile moteur, filtre à huile, révision, entretien voiture"),
              ("Freins", "freins, plaquettes, disques, freine mal, bruit de freins"),
              ("Embrayage et boîte de vitesses", "embrayage, boîte de vitesse, ne passe pas les vitesses, boîte automatique"),
              ("Suspension et train avant", "amortisseurs, train avant, rotules, cardan, bruit en roulant, parallélisme"),
              ("Électricité automobile", "batterie voiture, démarreur, alternateur, voiture ne démarre pas, phares, électricien auto"),
              ("Climatisation automobile", "clim voiture, recharge clim auto, clim auto ne refroidit pas"),
              ("Moteur, surchauffe et courroie", "surchauffe, voiture chauffe, radiateur, courroie de distribution, fuite d'huile, fumée"),
          ), aliases=("mecanique-automobile",)),
    Trade("auto-moto-velo", "depannage-remorquage", "Dépannage & remorquage", "fa-solid fa-truck-pickup",
          "dépanneuse, remorquage, panne sur la route, voiture en panne, remorquer", (
              ("Remorquage de véhicule", "dépanneuse, remorquer, tracter, plateau, véhicule accidenté"),
              ("Dépannage sur place", "panne sur la route, voiture en panne, mécanicien mobile, intervention rapide"),
              ("Démarrage de batterie", "batterie à plat, voiture ne démarre pas, booster, câbles"),
              ("Crevaison et changement de roue", "crevaison, pneu crevé, vulcanisateur, roue de secours, pneu"),
              ("Livraison de carburant", "panne sèche, plus d'essence, carburant, gasoil"),
          )),
    Trade("auto-moto-velo", "motos-scooters-velos", "Motos, scooters & vélos", "fa-solid fa-motorcycle",
          "moto, scooter, vélo, mécanicien moto, djakarta, tricycle", (
              ("Entretien et vidange de moto", "vidange moto, révision moto, entretien moto"),
              ("Réparation du moteur de moto", "moto ne démarre pas, moteur moto, carburateur, bougie"),
              ("Freins, chaîne et transmission", "chaîne, pignon, kit chaîne, freins moto"),
              ("Pneus et chambres à air", "crevaison moto, pneu moto, chambre à air, vulcanisation"),
              ("Électricité de moto", "batterie moto, phare moto, klaxon, démarreur moto"),
              ("Réparation de vélo", "vélo, bicyclette, crevaison vélo, dérailleur"),
              ("Réparation de tricycle", "tricycle, moto tricycle, cargo"),
          )),
    # ── Électricité & plomberie ──────────────────────────────────────────────────────────────────────────────────────
    Trade("electricite-plomberie", "electricite", "Électricité", "fa-solid fa-bolt",
          "électricien, courant, électricité, panne électrique, cie", (
              ("Dépannage de panne électrique", "plus de courant, court-circuit, disjoncteur saute, coupure, ça a sauté, fusible"),
              ("Installation électrique complète", "installation électrique, câblage maison, villa, appartement, mise aux normes"),
              ("Tableau électrique et disjoncteurs", "tableau électrique, disjoncteur, différentiel, coffret"),
              ("Prises, interrupteurs et éclairage", "prise, interrupteur, lampe, néon, spot, lustre, ampoule"),
              ("Raccordement et compteur CIE", "compteur, cie, branchement, compteur prépayé, abonnement électricité"),
              ("Groupe électrogène", "groupe électrogène, générateur, inverseur, groupe ne démarre pas"),
              ("Installation solaire", "panneau solaire, kit solaire, énergie solaire, batterie solaire, onduleur solaire"),
              ("Mise à la terre et parafoudre", "prise de terre, paratonnerre, parafoudre"),
          )),
    Trade("electricite-plomberie", "plomberie", "Plomberie", "fa-solid fa-faucet",
          "plombier, eau, tuyau, fuite, sodeci, sanitaire", (
              ("Réparation de fuite d'eau", "fuite, fuite d'eau, tuyau percé, robinet qui coule, dégât des eaux"),
              ("Débouchage de WC, d'évier et de canalisations", "wc bouché, toilettes bouchées, évier bouché, canalisation bouchée, mauvaise odeur"),
              ("Installation sanitaire", "wc, lavabo, douche, baignoire, évier, robinet, mitigeur"),
              ("Pompe et surpresseur", "surpresseur, pompe à eau, pression faible, pas d'eau, motopompe"),
              ("Réservoir et château d'eau", "château d'eau, réservoir, polytank, citerne, cuve"),
              ("Raccordement et compteur SODECI", "sodeci, compteur d'eau, branchement eau"),
              ("Installation de chauffe-eau", "chauffe-eau, ballon, eau chaude"),
              ("Fosse septique et puisard", "fosse septique, puisard, vidange de fosse, curage, regard"),
          )),
    # ── Bâtiment & rénovation ────────────────────────────────────────────────────────────────────────────────────────
    Trade("batiment-travaux", "batiment-renovation", "Bâtiment & rénovation", "fa-solid fa-helmet-safety",
          "maçon, chantier, construction, rénovation, travaux, btp", (
              ("Rénovation de maison et d'appartement", "rénovation, réfection, remise à neuf, travaux"),
              ("Construction : fondations, dalle, élévation", "construction, fondation, dalle, poteau, chaînage, villa, r+1"),
              ("Démolition et ouverture de mur", "démolition, casser un mur, ouverture, cassage"),
              ("Étanchéité de toiture et de terrasse", "étanchéité, infiltration, toit qui coule, fuite toiture, terrasse"),
              ("Faux plafond en staff ou en plâtre", "staff, faux plafond, plafond, corniche"),
              ("Fissures et humidité", "fissure, mur fissuré, humidité, moisissure, salpêtre"),
              ("Métré et suivi de chantier", "devis travaux, métré, chef de chantier, suivi de chantier"),
          )),
    # ── Menuiserie, métallerie & serrurerie ──────────────────────────────────────────────────────────────────────────
    Trade("bois-metal-serrurerie", "soudure-metallerie", "Soudure & métallerie", "fa-solid fa-fire-flame-curved",
          "soudeur, soudure, ferronnier, métallerie, fer, portail", (
              ("Portail et porte métallique", "portail, portail coulissant, porte en fer, porte métallique"),
              ("Grilles de protection", "grille, barreaux, grille de fenêtre, barreaudage, défense"),
              ("Garde-corps et rampes", "garde-corps, rampe d'escalier, balustrade"),
              ("Charpente et structure métallique", "charpente métallique, hangar, auvent, préau"),
              ("Soudure et réparation sur place", "soudure, ressouder, réparer un portail, poste à souder"),
              ("Menuiserie aluminium", "aluminium, fenêtre alu, baie vitrée, porte alu"),
          ), aliases=("ferronnerie", "soudure", "metallerie")),
    Trade("bois-metal-serrurerie", "menuiserie", "Menuiserie & mobilier", "fa-solid fa-hammer",
          "menuisier, bois, meuble, ébéniste", (
              ("Portes et fenêtres en bois", "porte en bois, fenêtre en bois, porte isoplane, chambranle"),
              ("Placards et cuisines sur mesure", "placard, cuisine équipée, dressing, meuble sur mesure"),
              ("Fabrication de meubles", "lit, armoire, table, chaise, bureau, meuble"),
              ("Réparation de meubles", "réparer un meuble, tiroir, charnière, pied cassé"),
              ("Escaliers, parquets et lambris en bois", "escalier en bois, parquet, lambris"),
          )),
    Trade("bois-metal-serrurerie", "serrurerie", "Serrurerie", "fa-solid fa-key",
          "serrurier, serrure, clé, clef, porte bloquée", (
              ("Ouverture de porte", "porte claquée, porte bloquée, clé perdue, clé cassée dans la serrure, enfermé dehors"),
              ("Changement de serrure et de cylindre", "changer la serrure, cylindre, barillet, canon"),
              ("Reproduction de clés", "double de clé, copie de clé"),
              ("Porte blindée et sécurisation", "porte blindée, verrou, sécuriser la porte, cambriolage"),
              ("Ouverture de coffre-fort", "coffre-fort, coffre fort bloqué, code oublié"),
              ("Réparation après effraction", "effraction, cambriolage, porte forcée"),
          )),
    # ── Nettoyage, entretien & jardin ────────────────────────────────────────────────────────────────────────────────
    Trade("entretien-jardin", "nettoyage-entretien", "Nettoyage & entretien", "fa-solid fa-broom",
          "nettoyage, entretien, propreté, agent d'entretien, société de nettoyage", (
              ("Nettoyage de maison et d'appartement", "grand ménage, nettoyage maison, nettoyage appartement"),
              ("Nettoyage de bureaux et de commerces", "nettoyage bureau, entretien des locaux, entreprise de nettoyage"),
              ("Nettoyage de canapés, matelas et tapis", "canapé, matelas, tapis, moquette, shampooing, injection extraction"),
              ("Nettoyage de vitres", "vitres, baies vitrées, façade"),
              ("Désinsectisation et dératisation", "cafards, punaises de lit, moustiques, rats, souris, termites, désinfection, fumigation"),
              ("Nettoyage de citerne et de réservoir", "citerne, château d'eau, réservoir, polytank"),
              ("Repassage et blanchisserie", "repassage, linge, pressing, blanchisserie"),
          ), aliases=("nettoyage",)),
    Trade("entretien-jardin", "jardinage", "Jardinage", "fa-solid fa-seedling",
          "jardinier, jardin, pelouse, gazon, espaces verts", (
              ("Tonte de gazon", "tondre, gazon, pelouse, herbe"),
              ("Taille de haies et d'arbustes", "haie, taille, arbuste, buisson"),
              ("Élagage et abattage d'arbres", "élagage, couper un arbre, abattage, branches, cocotier"),
              ("Entretien régulier de jardin", "entretien jardin, jardinier mensuel"),
              ("Création de jardin et plantations", "aménagement, plantation, fleurs, gazon synthétique"),
              ("Arrosage automatique", "arrosage, goutte à goutte, système d'arrosage"),
              ("Débroussaillage de terrain", "débroussailler, terrain, nettoyage de terrain, brousse"),
          )),
    # ── Couture, cordonnerie & tapisserie ────────────────────────────────────────────────────────────────────────────
    Trade("couture-cordonnerie", "couture-retouches", "Couture & retouches", "fa-solid fa-scissors",
          "couturier, couturière, tailleur, couture, pagne", (
              ("Retouches", "retouche, ourlet, raccourcir, ajuster, reprise, fermeture éclair"),
              ("Confection sur mesure", "tenue sur mesure, boubou, pagne, wax, robe, costume, tailleur"),
              ("Tenues de cérémonie et de mariage", "mariage, dot, baptême, tenue traditionnelle, kita"),
              ("Uniformes et tenues professionnelles", "uniforme, tenue scolaire, tenue de travail, blouse"),
              ("Couture à domicile", "couturière à domicile"),
          )),
    Trade("couture-cordonnerie", "cordonnerie", "Cordonnerie", "fa-solid fa-shoe-prints",
          "cordonnier, chaussures, sac, cuir", (
              ("Réparation de chaussures", "semelle, talon, recoller une chaussure, ressemelage, couture chaussure"),
              ("Réparation de sacs et d'articles en cuir", "sac, ceinture, portefeuille, fermeture, cuir"),
              ("Cirage et entretien du cuir", "cirage, lustrage, teinture chaussure"),
              ("Fabrication de sandales et de chaussures", "sandales, babouches, chaussures sur mesure"),
          )),
    Trade("couture-cordonnerie", "tapisserie", "Tapisserie & sellerie", "fa-solid fa-couch",
          "tapissier, salon, fauteuil, canapé, rembourrage", (
              ("Réfection de salon et de fauteuils", "refaire le salon, tissu canapé, mousse, rembourrage, fauteuil"),
              ("Rideaux et voilages", "rideaux, voilage, tringle, confection de rideaux"),
              ("Housses et coussins", "housse, coussin, housse de canapé"),
              ("Sellerie automobile", "siège de voiture, sellerie, housse de siège, garniture"),
              ("Matelas et têtes de lit", "matelas, tête de lit, capitonnage"),
          )),
    # ── Transport & déménagement ─────────────────────────────────────────────────────────────────────────────────────
    Trade("transport-demenagement", "demenagement", "Déménagement", "fa-solid fa-truck-ramp-box",
          "déménageur, déménager, camion, manutention", (
              ("Déménagement de maison ou d'appartement", "déménager, déménagement complet, villa, appartement"),
              ("Déménagement de bureaux", "bureaux, entreprise, transfert"),
              ("Manutention et chargement", "manutentionnaires, porteurs, charger un camion, décharger"),
              ("Démontage et remontage de meubles", "démonter, remonter, meubles"),
              ("Emballage et cartons", "cartons, emballage, film, protection"),
          )),
    Trade("transport-demenagement", "transport-livraison", "Transport & livraison", "fa-solid fa-truck",
          "transport, livraison, coursier, camion, tricycle, location de camion", (
              ("Transport de marchandises", "marchandises, fret, camion, bâché"),
              ("Location de camion avec chauffeur", "camion avec chauffeur, location camion, benne"),
              ("Livraison et coursier", "coursier, livraison, livreur, colis, moto de livraison"),
              ("Transport en tricycle", "tricycle, moto tricycle, petit transport"),
              ("Transport de matériaux de construction", "sable, gravier, ciment, briques, benne"),
          )),
    # ── Équipements professionnels ───────────────────────────────────────────────────────────────────────────────────
    Trade("equipements-professionnels", "maintenance-equipements-pro", "Maintenance d'équipements professionnels", "fa-solid fa-gears",
          "maintenance, équipement, technicien, entreprise, machine", (
              ("Groupes électrogènes industriels", "groupe électrogène, entretien de groupe, vidange groupe"),
              ("Équipements de cuisine professionnelle", "four professionnel, friteuse, restaurant, cuisine pro, hotte"),
              ("Photocopieurs et imprimantes professionnels", "copieur, multifonction, ricoh, kyocera"),
              ("Machines à coudre industrielles", "machine à coudre, surjeteuse, atelier de couture"),
              ("Pompes et motopompes", "pompe, motopompe, forage, surpresseur industriel"),
              ("Matériel de boulangerie et de pâtisserie", "pétrin, four à pain, boulangerie, laminoir"),
              ("Caisses et terminaux de paiement", "caisse enregistreuse, tpe, balance, lecteur code-barres"),
              ("Équipements de salon de coiffure et d'esthétique", "casque, fauteuil de coiffure, tondeuse, matériel de salon"),
          )),
)

# Métiers historiques rangés dans une famille (s'ils existent, sont des métiers et n'ont pas déjà de famille) — sans autre changement.
ATTACH: Dict[str, Sequence[str]] = {
    "informatique-numerique": ("assistance-informatique",),
    "electromenager-froid": ("installation-electromenager",),
    "auto-moto-velo": ("carrosserie", "lavage-auto"),
    "electricite-plomberie": ("chauffage",),
    "batiment-travaux": ("maconnerie", "carrelage", "peinture", "toiture", "platrerie", "isolation", "cloture", "terrasse", "pose-parquet",
                         "sol-pvc", "vitrerie", "bricolage"),
    "bois-metal-serrurerie": ("ebenisterie", "montage-meuble"),
    "entretien-jardin": ("menage", "nettoyage-apres-travaux", "paysagisme", "allee-jardin", "entretien-piscine"),
    "transport-demenagement": ("debarras", "chauffeur-prive"),
}


# ── Application ──────────────────────────────────────────────────────────────────────────────────────────────────────

def fold(text: str) -> str:
    """Comparaison sans accents, casse ni ponctuation : « Électricité » = « electricite »."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).casefold()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in plain).split())


def split_keywords(raw: str) -> List[str]:
    return [k.strip() for k in (raw or "").replace("\n", ",").split(",") if k.strip()]


def merge_keywords(current: str, extra: str) -> str:
    """Union stable : les synonymes déjà saisis restent en tête, les nouveaux s'ajoutent sans doublon (sans accents ni casse)."""
    out, seen = [], set()
    for k in split_keywords(current) + split_keywords(extra):
        key = fold(k)
        if key and key not in seen:
            seen.add(key)
            out.append(k)
    return ", ".join(out)


def _unique_slug(base: str, taken: set) -> str:
    base = (slugify(base) or "categorie")[:50].strip("-")
    slug, n = base, 2
    while slug in taken:
        suffix = f"-{n}"
        slug = base[:50 - len(suffix)].rstrip("-") + suffix
        n += 1
    taken.add(slug)
    return slug


def apply(apps=None, *, dry_run: bool = False) -> Counter:
    """Applique le référentiel (idempotent). `apps` : registre historique d'une migration ; sinon les modèles courants."""
    if apps is not None:
        FamilyModel = apps.get_model("handy", "CatalogFamily")
        Category = apps.get_model("handy", "ServiceCategory")
    else:
        from handy.models import CatalogFamily as FamilyModel, ServiceCategory as Category

    stats: Counter = Counter()
    families: Dict[str, object] = {}
    family_slugs = set(FamilyModel.objects.values_list("slug", flat=True))
    for f in FAMILIES:
        fam = FamilyModel.objects.filter(slug=f.slug).first() or next(
            (x for x in FamilyModel.objects.all() if fold(x.name) == fold(f.name)), None)
        if fam is None:
            stats["families_created"] += 1
            if not dry_run:
                fam = FamilyModel.objects.create(slug=_unique_slug(f.slug, family_slugs), name=f.name, icon=f.icon, position=f.position,
                                                 description=f.description, keywords=f.keywords, is_active=True)
        else:
            changes = {}
            if not fam.icon:
                changes["icon"] = f.icon
            if not fam.description:
                changes["description"] = f.description
            merged = merge_keywords(fam.keywords, f.keywords)
            if merged != fam.keywords:
                changes["keywords"] = merged
            if changes:
                stats["families_completed"] += 1
                if not dry_run:
                    FamilyModel.objects.filter(pk=fam.pk).update(**changes)
        families[f.slug] = fam

    taken = set(Category.objects.values_list("slug", flat=True))
    by_slug = {c.slug: c for c in Category.objects.all()}
    roots_by_name = {fold(c.name): c for c in Category.objects.filter(parent__isnull=True)}

    def find_trade(t: Trade):
        for slug in (t.slug, *t.aliases):
            c = by_slug.get(slug)
            if c is not None and c.parent_id is None:
                return c
        return roots_by_name.get(fold(t.name))

    for t in TRADES:
        fam = families.get(t.family)
        trade = find_trade(t)
        if trade is None:
            stats["trades_created"] += 1
            if dry_run:
                stats["prestations_created"] += len(t.prestations)
                continue
            trade = Category.objects.create(name=t.name, slug=_unique_slug(t.slug, taken), icon=t.icon, family=fam, keywords=t.keywords,
                                            is_active=True)
            by_slug[trade.slug] = trade
            roots_by_name[fold(trade.name)] = trade
        else:
            changes = {}
            if trade.family_id is None and fam is not None:
                changes["family"] = fam
            if not trade.icon:
                changes["icon"] = t.icon
            merged = merge_keywords(trade.keywords, t.keywords)
            if merged != trade.keywords:
                changes["keywords"] = merged
            if changes:
                stats["trades_completed"] += 1
                if not dry_run:
                    for k, v in changes.items():
                        setattr(trade, k, v)
                    trade.save(update_fields=list(changes))
            stats["trades_reused"] += 1
        children = {fold(c.name): c for c in Category.objects.filter(parent_id=trade.pk)}
        for index, (name, keywords) in enumerate(t.prestations):
            child = children.get(fold(name))
            if child is None:
                stats["prestations_created"] += 1
                if not dry_run:
                    child = Category.objects.create(name=name, slug=_unique_slug(name, taken), parent=trade, keywords=keywords,
                                                    position=(index + 1) * 10, is_active=True)
                    children[fold(name)] = child
                    by_slug[child.slug] = child
            else:
                merged = merge_keywords(child.keywords, keywords)
                if merged != child.keywords:
                    stats["prestations_completed"] += 1
                    if not dry_run:
                        Category.objects.filter(pk=child.pk).update(keywords=merged)

    for family_slug, slugs in ATTACH.items():
        fam = families.get(family_slug)
        for slug in slugs:
            c = by_slug.get(slug)
            if c is not None and c.parent_id is None and c.family_id is None and fam is not None:
                stats["trades_attached"] += 1
                if not dry_run:
                    Category.objects.filter(pk=c.pk).update(family=fam)
    return stats


def summary(stats: Counter) -> str:
    labels = (("families_created", "familles créées"), ("families_completed", "familles complétées"), ("trades_created", "métiers créés"),
              ("trades_reused", "métiers existants réutilisés"), ("trades_completed", "métiers complétés"), ("trades_attached", "métiers rangés dans une famille"),
              ("prestations_created", "prestations créées"), ("prestations_completed", "prestations complétées (synonymes)"))
    return " · ".join(f"{stats.get(k, 0)} {label}" for k, label in labels)
