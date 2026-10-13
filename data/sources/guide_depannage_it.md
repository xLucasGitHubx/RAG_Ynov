---
titre: Guide de dépannage informatique
fichier: guide_depannage_it.md
format: md
categorie: IT
version: "2026.1"
date_effet: "2026-02-01"
statut: en_vigueur
sources: >-
  Rédigé par l'équipe projet, cohérent avec la charte informatique Nexalis et les recommandations
  de l'ANSSI (guide d'hygiène informatique). Noms d'outils et procédures fictifs.
---

# Guide de dépannage informatique

Nexalis Conseil — Service informatique, version 2026.1 (février 2026).

Avant d'ouvrir un ticket, consultez ce guide : il couvre les demandes les plus fréquentes. Le support informatique est joignable au **poste 4242** (numéro externe affiché sur l'intranet) du lundi au vendredi de **8 h 00 à 19 h 00**, et via le portail « Nexalis Service Desk ». En dehors de ces horaires, une astreinte traite uniquement les incidents bloquants pour la production client.

## 1. VPN : se connecter à distance

Le VPN de l'entreprise s'appelle **Nexalis Connect**. Il est obligatoire pour accéder aux applications internes depuis l'extérieur (domicile, client, hôtel, train).

### 1.1 Première connexion

1. Ouvrez l'application Nexalis Connect (icône en forme de bouclier dans la barre des tâches).
2. Saisissez votre identifiant au format prenom.nom.
3. Saisissez votre mot de passe Windows.
4. Validez la notification MFA sur votre téléphone.
5. Le bouclier devient vert : vous êtes connecté.

### 1.2 Le VPN ne se connecte pas

1. Vérifiez votre connexion internet en ouvrant un site public.
2. Sur un Wi-Fi d'hôtel ou de gare, ouvrez d'abord le navigateur pour accepter les conditions du portail d'accès, puis relancez le VPN.
3. Redémarrez l'application Nexalis Connect (clic droit sur le bouclier, « Quitter », puis relancer).
4. Si le message « Certificat expiré » apparaît, l'ordinateur ne s'est pas connecté au réseau de l'entreprise depuis plus de 90 jours : passez sur site ou ouvrez un ticket pour un renouvellement à distance.
5. Si le problème persiste après un redémarrage de l'ordinateur, ouvrez un ticket en précisant le message d'erreur exact.

### 1.3 Le VPN se déconnecte souvent

La session VPN se coupe automatiquement après **10 heures** de connexion ou **30 minutes** d'inactivité. Sur une connexion 4G instable, activez l'option « Reconnexion automatique » dans les paramètres de Nexalis Connect.

## 2. MFA : authentification multifacteur

L'authentification multifacteur utilise l'application **Microsoft Authenticator**.

### 2.1 Changement de téléphone

1. Avant de rendre ou réinitialiser l'ancien téléphone, connectez-vous à la page « Mes informations de sécurité » depuis votre ordinateur.
2. Cliquez sur « Ajouter une méthode », puis « Application d'authentification ».
3. Scannez le QR code avec le nouveau téléphone.
4. Supprimez l'ancien téléphone de la liste.

Si l'ancien téléphone est perdu ou cassé, appelez le support (poste 4242) : après vérification de votre identité par votre manager, le technicien réinitialise votre MFA.

### 2.2 Je ne reçois plus les notifications

Vérifiez que le téléphone a accès à internet et que les notifications de Microsoft Authenticator sont autorisées. En attendant, utilisez le code à 6 chiffres affiché dans l'application.

Si vous recevez une demande MFA que vous n'avez pas initiée, **refusez-la** et signalez-la immédiatement au support : quelqu'un connaît peut-être votre mot de passe.

## 3. Mot de passe

### 3.1 Mot de passe oublié ou compte verrouillé

Le compte est verrouillé après 5 tentatives infructueuses ; il se déverrouille automatiquement après **15 minutes**.

Pour réinitialiser votre mot de passe vous-même :

1. Sur l'écran de connexion Windows, cliquez sur « Mot de passe oublié ? », ou depuis un autre appareil, ouvrez le portail de réinitialisation en libre-service.
2. Validez votre identité avec la MFA.
3. Choisissez un nouveau mot de passe conforme à la charte (12 caractères minimum).

Si vous êtes hors site, connectez-vous ensuite au VPN pour synchroniser le nouveau mot de passe avec votre poste.

### 3.2 Changer son mot de passe

Appuyez sur Ctrl + Alt + Suppr, puis « Modifier un mot de passe ». Le nouveau mot de passe ne doit pas être l'un des 5 derniers utilisés.

## 4. Imprimantes

Les imprimantes multifonctions fonctionnent en **impression sécurisée** : les documents ne sortent qu'après badge sur l'imprimante.

### 4.1 Installer une imprimante

Ouvrez le Centre logiciel, puis installez « Impression Nexalis ». La file d'impression unique « Nexalis-Print » fonctionne sur toutes les imprimantes de Toulouse et de Paris.

### 4.2 Mon document ne sort pas

1. Vérifiez que vous êtes connecté au réseau de l'entreprise (sur site ou via VPN).
2. Badgez sur l'imprimante et sélectionnez « Mes impressions ».
3. Les documents non imprimés sont supprimés automatiquement après **24 heures**.
4. En cas de bourrage papier ou de toner vide, signalez-le à l'accueil du site.

## 5. Messagerie et Teams

- **Boîte aux lettres pleine** : la boîte est limitée à 50 Go. Videz le dossier « Éléments supprimés » et activez l'archivage en ligne.
- **Teams ne démarre pas** : quittez Teams, videz le cache (dossier `%appdata%\Microsoft\Teams`), puis relancez.
- **Absence prolongée** : programmez un message d'absence dans Outlook (Fichier > Réponses automatiques).

## 6. Matériel

- **Écran supplémentaire, clavier, souris** : demande via le portail Nexalis Service Desk, livraison sous 5 jours ouvrés.
- **Ordinateur lent** : redémarrez (un redémarrage par semaine minimum est recommandé) et vérifiez l'espace disque disponible.
- **Ordinateur perdu ou volé** : appelez le support **dans l'heure** (voir la charte informatique, article 7).
- **Renouvellement** : les ordinateurs portables sont renouvelés tous les **4 ans**.

## 7. Ouvrir un ticket efficacement

Indiquez dans le ticket :

- le nom de l'ordinateur (inscrit sur l'étiquette, format NXL-XXXX) ;
- le message d'erreur exact ou une capture d'écran ;
- ce que vous avez déjà essayé ;
- l'urgence : bloquant, gênant ou demande d'information.

Délais de prise en charge : bloquant 1 heure, gênant 4 heures ouvrées, demande d'information 2 jours ouvrés.
