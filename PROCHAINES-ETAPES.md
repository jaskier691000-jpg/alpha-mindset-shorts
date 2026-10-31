# Alpha Mindset : ce qu'il reste à faire

La chaîne publie 2 vidéos par jour (vers 8h et 20h, heure de Paris) sur TikTok et Instagram, toute seule,
grâce à GitHub (montage) et Zernio (publication). Ton PC n'est pas nécessaire une fois tout en place.

## 1. Les comptes (à faire par toi, avec une adresse email dédiée à Alpha Mindset)

1. **Email** : crée une nouvelle adresse pour la chaîne.
2. **TikTok** : compte **personnel** (jamais « entreprise », sinon pas de rémunération), mot de passe, photo, bio
   (sans heures de publication).
3. **Instagram** : passe le compte en **Créateur** (Paramètres → Type de compte et outils), catégorie Éducation.
   N'active pas « profil généré par IA ».
4. **GitHub** : nouveau compte avec ce mail, puis un dépôt **vide** (sans README) nommé `alpha-mindset-shorts`,
   **public** (minutes gratuites illimitées ; tes clés restent secrètes).
5. **Zernio** : nouveau compte gratuit, connecte TikTok et Instagram.
6. **Pixabay** : compte avec ce mail ; ta clé est affichée sur pixabay.com/api/docs une fois connecté.
7. **Musique** : 5 à 10 musiques sur Pixabay Music, épiques ou sombres (motivation, trailer), plus de 90 s, sans paroles.

Dis à Claude quand c'est fait. Ne colle jamais une clé dans la conversation.

## 2. Les clés sur GitHub (à faire par toi)

Sur github.com → ton dépôt → Settings → Secrets and variables → Actions → New repository secret :

| Nom | Où la trouver |
|---|---|
| `ZERNIO_API_KEY` | zernio.com → API keys |
| `PIXABAY_API_KEY` | pixabay.com/api/docs |
| `TELEGRAM_BOT_TOKEN` | le même bot que tes autres chaînes |
| `TELEGRAM_CHAT_ID` | le même chat que tes autres chaînes (secret ici car le dépôt est public) |

Une fois enregistrée, une clé n'est plus jamais affichée (case vide = normal).

## 3. La tâche du lundi (Claude écrit les monologues)

github.com/apps/claude → Configure → ton nouveau compte → accès au seul dépôt `alpha-mindset-shorts`.
Sans ça, Claude ne peut pas créer la tâche du lundi (erreur 403).

## 4. Les tests, puis la mise en ligne (avec Claude)

1. Une vidéo d'exemple faite par le vrai système automatique : tu valides.
2. Sur GitHub (onglet Actions → « Daily Alpha Mindset videos » → Run workflow) : `no-publish`, puis `dry-run`.
3. Un passage en **brouillon** (`publish_mode: draft`) : la vidéo arrive dans la boîte de réception de l'appli TikTok.
   Supprime les brouillons, ne les publie pas.
4. Tu donnes ton accord → `publish_mode: schedule` → la chaîne tourne seule.

## À savoir

- **Étiquette IA** : les plans de la bibliothèque cinéma sont des images IA réalistes ; TikTok exige alors l'étiquette
  « contenu généré par IA ». Le système la coche automatiquement (à vérifier au test brouillon).
- **Voix** : Chatterbox Nano (gratuite, open source) avec une voix grave de référence libre de droits.
- **Images** : moitié bibliothèque cinéma IA (fabriquée une fois sur ton PC), moitié vraies vidéos Pixabay.
- **Rappels Telegram** : un message à chaque vidéo programmée, à chaque publication, et en cas de problème
  (connexion Instagram à renouveler tous les ~60 jours, sujets écrits qui s'épuisent…).
