# wled-usb — piloter WLED en USB, sans WiFi

[![Licence](https://img.shields.io/badge/licence-EUPL--1.2-blue.svg)](LICENSE)
![WLED](https://img.shields.io/badge/WLED-16.0.1-00b894.svg)
![Pont](https://img.shields.io/badge/pont-Python%203.10%2B-3776ab.svg)
![App](https://img.shields.io/badge/app-macOS%2014.2%2B%20Apple%20Silicon-000000.svg)

Pilote un module WLED **uniquement par USB**, sans aucun accès réseau au module,
et sert l'**interface web officielle de WLED** en local.

- **Rien sur le réseau.** Le module n'y entre jamais ; tout passe par le câble.
- **La vraie interface WLED**, servie en local — effets, palettes, segments, presets, aperçu live.
- **Réaction au son** de l'ordinateur, sans micro et sans pilote.
- **Flash du firmware** par le même câble, le pont s'effaçant devant esptool.
- **Une app macOS de barre des tâches** qui embarque son Python : rien à installer à côté.

*[English version](README.md) · l'interface elle-même est bilingue (anglais/français)
et suit la langue de l'ordinateur.*

Le firmware WLED écoute du JSON sur son port série : tout objet commençant par `{`
est passé à `deserializeState()`, et `{"v":true}` fait répondre l'état complet.
Le pont traduit les requêtes HTTP de l'UI officielle vers ce canal série.

Développé et testé sur WLED 16.0.1, ESP32-PICO-D4, 144 LEDs, macOS 27 sur Apple
Silicon. Le pont lui-même n'a rien de spécifique à macOS ; l'application de barre des
menus décrite plus bas, si.

## Sommaire

Compiler et lancer l'app macOS, c'est dans [Application macOS](#application-macos) — c'est loin.

- [Installation](#installation)
- [Ce qui fonctionne](#ce-qui-fonctionne)
- [Ce qui n'est pas possible, et pourquoi](#ce-qui-nest-pas-possible-et-pourquoi)
- [Mise à jour du firmware par USB](#mise-à-jour-du-firmware-par-usb)
- [Données statiques](#données-statiques)
- [Interface vendorisée](#interface-vendorisée)
- [Langue](#langue)
- [Application macOS](#application-macos)
  - [Compiler et lancer](#compiler-et-lancer)
  - [Signature](#signature)
- [Déclencheurs macOS](#déclencheurs-macos)
- [Son du Mac vers les LEDs](#son-du-mac-vers-les-leds)
- [Streaming audio-réactif (LedFx, Adalight)](#streaming-audio-réactif-ledfx-adalight)
- [Notifications](#notifications)
  - [Notifications pendant le son réactif](#notifications-pendant-le-son-réactif)
- [Architecture](#architecture)
- [Sécurité](#sécurité)
- [Comment ce projet a été écrit](#comment-ce-projet-a-été-écrit)
- [Licence et crédits](#licence-et-crédits)

## Installation

Python 3.10 ou plus récent, et un module WLED relié en USB.

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./run.sh --open
```

Le port série est détecté automatiquement. Options utiles :

| Option | Effet |
| --- | --- |
| `--list-ports` | liste les ports série candidats et quitte |
| `--port /dev/cu.xxx` | force le port |
| `--http-port 8723` | port HTTP (défaut 8723) |
| `--listen localhost` | adresses d'écoute (défaut : boucle locale seulement) |
| `--lang fr` | langue de l'interface au premier lancement |
| `--kdeconnect` | notifications du téléphone via KDE Connect (désactivé par défaut) |
| `--poll 2.0` | intervalle de rafraîchissement de l'état, en secondes |
| `--baud 115200` | débit série |

Le port série est pris en **exclusivité** : une seconde instance du pont, un moniteur
série ou LedFx lancé en parallèle est refusé avec un message explicite au lieu de se
partager silencieusement le flux. Sans ce verrou, les deux lecteurs se volent les
réponses et l'interface reste vide alors que la liaison paraît « connectée ».

Deux pages :

- `http://127.0.0.1:8723/` — l'interface WLED officielle ;
- `http://127.0.0.1:8723/bridge` — état de la liaison, presets, flash firmware.

## Ce qui fonctionne

Tout le contrôle temps réel : alimentation, luminosité, couleurs, effets, palettes,
vitesse/intensité, segments, nightlight, transitions, chargement de presets.
Les listes d'effets et de palettes, leurs métadonnées de curseurs et les dégradés
d'aperçu sont servis par le pont (voir *Données statiques*), la prévisualisation
live des pixels aussi.

| Endpoint | Source |
| --- | --- |
| `/json/si`, `/json/state`, `/json/info` | port série, en direct |
| `POST /json`, `/json/state`, `/json/si` | port série, en direct |
| `/json/effects`, `/json/palettes`, `/json/fxdata`, `/json/palx` | base statique générée |
| `/json/live` et trames binaires WebSocket | commande série `L` (lecture des pixels) |
| `/presets.json` | cache local du pont |
| `/ws` | diffusion d'état + commandes + liveview |

## Ce qui n'est pas possible, et pourquoi

Le handler série de WLED n'appelle que `deserializeState()`. **La configuration
(`deserializeConfig`) n'est jamais atteinte par le port série.** Les pages de
réglages, l'éditeur de fichiers et la mise à jour OTA ne vivent que dans le serveur
HTTP du module, hors d'atteinte ici. Ces URL renvoient une page d'explication.

Pour changer un réglage durable (nombre de LEDs, broche, Wi-Fi…), il faut passer par
le réseau une fois, ou reflasher une image qui embarque la configuration voulue.

### Presets

Les *noms* de presets sont dans `/presets.json` sur le système de fichiers du module,
illisible par le port série. Le pont maintient donc son propre cache :

- un preset chargé depuis l'interface est mémorisé automatiquement ;
- la page `/bridge` permet de **détecter** les emplacements occupés (1 à N) et de les
  **renommer localement** — ce renommage n'écrit rien sur le module ;
- enregistrer un preset depuis l'interface WLED (`psave`) écrit bien sur le module
  *et* met le cache à jour.

Attention : dans l'interface officielle, renommer un preset le **ré-enregistre** avec
l'état courant. Pour un simple libellé, utilisez le renommage local de `/bridge`.

## Mise à jour du firmware par USB

La page `/bridge` flashe via le bootloader série de l'ESP32 (esptool). Le pont libère
le port pendant l'opération puis le reprend.

- **Tester le bootloader** lance un `flash-id` : aucune écriture, vérifie seulement que
  la carte entre bien en mode bootloader.
- Le flash écrit par défaut la seule **application** en `0x10000` : bootloader, table de
  partitions, système de fichiers et configuration sont conservés.
- Pour une image complète fusionnée, mettre l'adresse à `0x0`.
- Le fichier est refusé s'il ne commence pas par la signature ESP `0xE9`.

Images officielles : `WLED_<version>_ESP32.bin` dans les releases GitHub du projet WLED.
Vérifier le `sha256` annoncé par l'API GitHub avant d'écrire.

> [!IMPORTANT]
> Après un flash vers une autre version de WLED, régénérez la base statique (ci-dessous),
> sinon les noms d'effets seront décalés. La page `/bridge` signale l'écart.

### Sauvegarde et retour arrière

Avant de reflasher, garder de quoi revenir en arrière : une image intégrale du flash,
l'état du module (`/json`) et la base d'effets de la version en place.

> [!CAUTION]
> `backup/` est **exclu du dépôt** par `.gitignore`, et doit le rester. Une image
> intégrale contient la partition NVS, où l'ESP32 stocke le SSID et la clé Wi-Fi en
> clair, ainsi que l'adresse MAC du module. C'est une sauvegarde personnelle, pas un
> artefact de projet.

Lecture d'une image complète et restauration :

```bash
./.venv/bin/python -m esptool --chip esp32 --port /dev/cu.usbserial-XXXX --baud 115200 \
  read-flash 0 0x400000 backup/flash-complet.bin
./.venv/bin/python -m esptool --chip esp32 --port /dev/cu.usbserial-XXXX --baud 115200 \
  write-flash 0x0 backup/flash-complet.bin
```

Arrêter le pont avant : il garde le port en exclusivité. Certains adaptateurs USB-série
n'arrivent pas à changer de débit une fois le stub chargé ; 115200 passe toujours,
n'augmenter que si le vôtre l'accepte.

### Passage d'une version majeure à la suivante

Écrire la seule application ne conserve la configuration **que si la version flashée
attend la table de partitions déjà en place**. WLED publie plusieurs dispositions ESP32,
qui diffèrent par la taille du système de fichiers et par la place laissée à
l'application, et un binaire de release est construit pour l'une d'elles. Flasher une
application plus grosse que la partition en place déborde sur la suivante ; en flasher une
construite pour une autre taille de système de fichiers, et le firmware cherche ses
fichiers là où ils ne sont pas.

Deux champs de `GET /json/info` disent ce qui tourne :

| Champ | Se lit |
| --- | --- |
| `fs.t` | taille du système de fichiers en ko, qui suit la table de partitions — 983 sur une disposition 1 Mo |
| `core` | la version d'ESP-IDF avec laquelle l'application en place a été construite |

Si les dispositions ne correspondent pas, écrire l'ensemble complet — bootloader en
`0x1000`, table de partitions en `0x8000`, application en `0x10000` — en acceptant d'y
laisser la configuration.

Une version majeure change aussi l'ESP-IDF sur lequel l'application est construite, alors
que le bootloader en flash reste celui écrit avec l'ancienne. L'ESP32 tolère cet attelage
en pratique, mais rien ne le garantit : si le module ne revient pas, écrire aussi le
bootloader correspondant.

> [!NOTE]
> Un chemin mesuré, qui ne garantit pas le vôtre : 0.15.x vers 16.0.1 sur un
> ESP32-PICO-D4, les deux versions sur `WLED_ESP32_4MB_1MB_FS.csv`, application seule en
> `0x10000`, ESP-IDF 3.3 vers 4.4.8 en laissant le bootloader de la 0.15. Le module a
> démarré et gardé ses réglages.

## Données statiques

`data/wled-data.json` contient les noms d'effets, leurs métadonnées de curseurs, les noms
de palettes et les dégradés d'aperçu pour une version de WLED — 220 effets et 72 palettes
en 16.0.1. Ces données sont extraites des sources WLED taguées, pas saisies à la main :

```bash
./.venv/bin/python tools/gen-data.py v16.0.1      # télécharge les sources du tag et régénère
./.venv/bin/python tools/gen-data.py --src ./srcs # depuis des sources locales
```

Le générateur lit `FX.h` (indices `FX_MODE_*`), les chaînes `_data_FX_MODE_*` de `FX.cpp`
dans l'ordre d'enregistrement de `setupEffectData()`, `JSON_palette_names` de `FX_fcn.cpp`,
les dégradés et les palettes 16 couleurs. Il reproduit la logique de `serializeModeNames`,
`serializeModeData` et `serializePalettes` de WLED.

Les deux dispositions de sources sont reconnues. Jusqu'à la 0.15.x les dégradés sont dans
`wled00/palettes.h` et les palettes 16 couleurs viennent de FastLED. À partir de la 16.x
FastLED n'est plus une dépendance : tout est dans `wled00/palettes.cpp`, et les noms de
couleurs dans `wled00/src/dependencies/fastled_slim/fastled_slim.h`. Le générateur choisit
en testant la présence de `palettes.h` sur le tag demandé.

Le pont compare `fxcount`, `palcount` et `ver` remontés par le module avec cette base
et signale toute divergence dans `/bridge/status`.

## Interface vendorisée

`vendor/` contient l'UI officielle WLED **16.0.1**, prise dans `wled00/data/` à ce tag.
La version de l'UI n'a pas à correspondre au firmware : les listes d'effets et de palettes
viennent du pont, pas de la page, donc une UI plus ancienne pilote très bien un module plus
récent. Deux modifications :

```
index.js  : "ws://"+window.location.hostname+"/ws"
         →  "ws://"+window.location.host+"/ws"

index.htm : bouton « Bridge » ajouté dans la barre du haut, après « Config »
```

L'UI suppose d'être servie sur le port 80 et perdait le port dans l'URL WebSocket.

WLED 16 a ajouté une vérification de version qui peut envoyer des détails sur l'appareil
à `usage.wled.me`. À chaque chargement de page elle lit
`/edit?func=edit&path=/version-info.json` ; un changement de version lit ensuite
`/json/cfg` et envoie le rapport — derrière une fenêtre de confirmation, ou directement si
un choix « toujours signaler » a été enregistré sur l'appareil.

Le firmware saute l'ensemble quand le module se déclare en mode point d'accès. Ne pas s'y
fier ici : un module qui garde des identifiants Wi-Fi et se connecte à un réseau se
déclare en mode station, et la vérification s'exécuterait. Ce qui l'arrête sur ce pont,
c'est la réponse elle-même — `/edit` fait partie des endpoints servis en page HTML
d'explication, donc `res.json()` échoue et le handler part dans son `catch`, qui n'ouvre
rien et n'envoie rien.

Mesuré en forçant le chemin « mode station » sur une page chargée : `/edit` a répondu 200,
le parse a levé `Unexpected token '<'`, le catch a réécrit le fichier de version par un
`POST /upload` auquel le pont a répondu 404, aucune fenêtre ne s'est ouverte, et rien n'est
parti vers `usage.wled.me`.

Le bouton « Bridge » ouvre `/bridge` ; la page `/bridge` a son propre lien de retour. Son
icône `⇄` n'appartient pas à la police `WIcons` de WLED, qui ne contient que ses propres
glyphes : `public/skin.css` la repasse donc en police courante. Ce fichier est le point
d'entrée prévu par WLED pour personnaliser le thème, servi tel quel par le pont.

## Langue

L'interface existe en **anglais (défaut) et en français**. Au premier lancement le pont
choisit la langue d'après la locale de l'ordinateur ; le sélecteur en haut à droite de
`/bridge` l'emporte ensuite, et le choix est enregistré puis partagé par la page web et
le menu de la barre des tâches.

Les noms de rendus et de palettes sont des clés anglaises stables côté API (`spectrum`,
`bass`, `rainbow`, `forest`…), traduites seulement à l'affichage : changer de langue ne
perd aucun réglage. Les messages du terminal sont en anglais uniquement.

## Application macOS

`app/` produit un `WLED USB.app` autonome : il embarque son propre CPython, lance le
pont, capte le son système et installe un menu dans la barre des tâches. Rien à installer
à côté — ni Python, ni environnement virtuel, ni Homebrew.

**Prérequis :** un Mac Apple Silicon sous macOS 14.2 ou plus récent, et les outils en
ligne de commande Xcode pour `swiftc` (`xcode-select --install`).

### Compiler et lancer

```bash
./app/build.sh
```

La première compilation télécharge un CPython relocalisable (27 Mo), vérifie son
empreinte SHA-256, y installe pyserial et esptool, compile le Swift et signe le bundle.
Les suivantes réutilisent l'interpréteur et prennent quelques secondes. Le résultat est
`app/build/WLED USB.app`, environ 90 Mo.

```bash
open "app/build/WLED USB.app"
```

Elle n'a ni fenêtre ni icône dans le Dock au départ : cherchez la mascotte dans la
**barre des menus**, à droite. Le menu affiche l'état du pont, celui du son et un
vumètre.

Au premier lancement :

1. **Ouvrir l'interface** depuis le menu — l'UI WLED s'ouvre dans une fenêtre, et c'est
   seulement à ce moment que l'app apparaît dans le Dock.
2. **Activer le son de l'ordinateur** depuis le menu — macOS demande l'autorisation
   *enregistrement audio du système* la première fois. La capture ne démarre jamais seule.
3. Cocher un déclencheur sous **Déclencheurs** ne demande le calendrier que pour celui
   des réunions.

Les réglages vivent dans `~/Library/Application Support/WLED USB/` : `audio.json`,
`ui.json`, `presets.json` et `notifications.json`. Supprimer ce dossier remet l'app à
zéro. Deux comportements se règlent hors de l'interface, avec des défauts adaptés à une
installation neuve :

```bash
defaults write fr.wledusb.app listen "localhost,tailscale"
defaults write fr.wledusb.app kdeconnect -bool true
```

### Signature

Le build signe avec un certificat auto-signé nommé `WLED USB Dev`, et retombe sur une
signature à la volée avec un avertissement s'il n'en trouve pas. Ça marche, mais
l'identité du bundle change à chaque reconstruction, donc **macOS redemande
l'autorisation audio à chaque fois**. Cinq minutes bien employées.

Créez-en un dans *Certificate Assistant*, qui n'est pas dans Applications :

```bash
open "/System/Library/CoreServices/Certificate Assistant.app"
```

Choisissez *Créer un certificat*, nommez-le exactement `WLED USB Dev`, type d'identité
*Racine auto-signée*, type de certificat **Signature de code**. Un certificat auto-signé
n'est pas approuvé pour signer tant que vous ne le dites pas, ce qui demande votre mot de
passe :

```bash
sudo security add-trusted-cert -d -r trustRoot -p codeSign -k /Library/Keychains/System.keychain ~/Desktop/wled-cert.pem
```

Exportez-le d'abord vers ce chemin :

```bash
security find-certificate -c "WLED USB Dev" -p > ~/Desktop/wled-cert.pem
```

Puis contrôlez que c'est pris :

```bash
security find-identity -v -p codesigning
```

`WLED_SIGN_IDENTITY` surcharge le nom si vous avez déjà votre propre certificat.

Certificate Assistant demande une adresse e-mail et l'inscrit dans le certificat, qui se
retrouve dans le bundle signé. Elle reste sur votre machine tant que vous ne donnez l'app
à personne ; prenez une adresse que vous accepteriez de voir si cela arrivait.

## Déclencheurs macOS

macOS n'offre **aucune API pour lire les notifications d'autres applications** : ni
`UserNotifications`, qui ne voit que les siennes, ni `DistributedNotificationCenter`, trop
limité. C'est un choix de conception d'Apple. Slack sur Mac reste donc hors de portée,
quelle que soit la langue dans laquelle on écrit l'app.

Ce qui est observable sans aucune autorisation, en revanche, l'app le surveille. Chaque
déclencheur s'active séparément dans le menu, et poste sur `/bridge/notify` comme le ferait
`notify.sh`.

| déclencheur | source | motif |
| --- | --- | --- |
| Réveil du Mac | `NSWorkspace.didWakeNotification` | `info` |
| Verrouillage / déverrouillage | `com.apple.screenIsLocked` / `…Unlocked` | `info` |
| Une app surveillée démarre ou se ferme | `NSWorkspace.did{Launch,Terminate}Application` | `chat` |
| Tailscale ou NetBird tombe | balayage `getifaddrs` d'une adresse en `100.64/10` | `urgent` |
| Réunion dans 5 minutes | EventKit | `call` |

La liste des applications surveillées se choisit dans *Déclencheurs → Applications
surveillées* : le sous-menu liste les apps en cours avec celles déjà cochées, et la
sélection est gardée dans les préférences de l'app.

Seule la réunion demande une autorisation — celle du calendrier, étroite et révocable.
Elle n'est demandée qu'au moment où vous cochez la ligne, jamais au lancement.

### Schéma d'URL

L'app enregistre `wledusb://`, ce qui met le ruban à portée de n'importe quoi : un script,
une automatisation, un Stream Deck, ou l'action **Ouvrir l'URL** de Raccourcis.

```bash
open "wledusb://notify?pattern=chat&title=Build%20termin%C3%A9&app=CI"
```

Paramètres : `pattern`, `title`, `app`, `priority`. C'est la même file que les
notifications KDE Connect, donc les priorités et les anti-répétitions s'appliquent.

## Son du Mac vers les LEDs

L'audio sync de WLED passe par UDP et n'existe pas sur le port série : `handleSerial()`
ne connaît que l'Adalight, le TPM2, l'Improv et le JSON. L'analyse se fait donc côté Mac,
et seuls des pixels descendent le câble.

```
app (Swift)  ──tap Core Audio──▶ FFT vDSP ──24 bandes──▶ pont (Python) ──Adalight──▶ module
```

L'app ouvre un *Core Audio process tap* : ni pilote, ni mot de passe administrateur, et
l'autorisation demandée est « enregistrement audio du système », pas l'écran. Elle capte
le mix quel que soit le périphérique de sortie, casque compris, sans périphérique de
sortie multiple à fabriquer. La capture ne démarre que sur clic dans le menu.

Les bandes arrivent sur l'entrée standard du pont (`--audio-stdin`), trames
`A5 5A <n> <rms> <n octets>`.

Chaque bande est normalisée séparément : le moteur garde un plafond glissant par
bande et ramène le niveau dessus. Sans ça, les graves saturent pendant que les aigus restent
noirs, et le ruban ne bouge presque pas. Les pixels gardent une traîne (`PIXEL_DECAY`)
pour adoucir le scintillement.

Les palettes sont des rampes de couleurs **saturées**, pas des dégradés sombre-vers-clair :
la luminosité vient du niveau sonore, pas de la rampe. Une première teinte sombre
assombrirait la zone des graves, qui est justement la plus visible.

Normaliser ne suffit pas : le ruban ne suivait plus que les gros écarts. Deux réglages
rattrapent les petites variations, visibles dans le panneau `/bridge` :

| réglage | rôle |
| --- | --- |
| `curve` (finesse) | exposant appliqué au niveau normalisé. Plus il est bas, plus les faibles niveaux remontent : à 0,55, un niveau de 0,02 s'affiche à 0,19 au lieu de rester noir. |
| `palette` | rampe de couleurs du rendu : `rainbow`, `ember`, `ocean`, `forest`, `neon`, `ice`, `sunset`. |
| `floor` (plancher) | lueur de fond appliquée **en sortie**, sur les LEDs que le rendu laisse noires. |
| `auto` (gain automatique) | ajuste le gain tout seul selon le volume de la source. Le curseur `gain` devient alors le taux de remplissage visé aux crêtes. |

Une porte de présence, calée sur le RMS brut, garde le ruban éteint au silence — sans
elle, le plancher allumerait les LEDs en permanence.

La normalisation par bande gomme le **timbre**, pas le **volume** : un podcast et un
morceau masterisé fort n'arrivent pas au même niveau, et il fallait reprendre le curseur
de gain à chaque fois. Le gain automatique ferme cette boucle. Chaque rendu déclare dans
`DRIVES` la grandeur qu'il multiplie par le gain — crête des bandes pour `spectrum`,
moyenne des graves pour `bass`, etc. — et le moteur suit cette grandeur avec un
détecteur de crête à attaque rapide (0,3 par image) et relâchement lent (0,01, soit
quelques secondes). Le gain appliqué vaut `gain × (1 / enveloppe)`, borné entre 0,4× et
6×, et affiché en direct sous le curseur.

L'asymétrie attaque/relâchement est ce qui compte : descendre vite évite de saturer sur
un coup de grosse caisse, remonter lentement évite de pomper entre deux couplets. La
boucle est gelée tant que la porte de présence est fermée, sinon le gain partirait au
plafond pendant les silences et le premier son reviendrait en pleine face.

Deux leçons tirées à l'usage. Le plancher a d'abord été appliqué au **niveau**, avant le
rendu : sans effet visible, puisque `spectrum` et `bass` encodent l'énergie en longueur
de barre et que 3 % d'une zone font un tiers de LED. Il agit maintenant sur les pixels
noirs en sortie, donc dans tous les rendus.

Et normaliser chaque bande sur son propre maximum supprime le relief entre bandes : le
ruban s'allume uniformément et ne raconte plus rien. `AGC_MIX` garde 35 % du niveau
absolu pour que les graves restent plus forts que les aigus.

| rendu | ce qu'il fait |
| --- | --- |
| `spectrum` | six barres en miroir depuis le centre, une par groupe de fréquences |
| `bass` | barre qui grandit depuis le centre selon l'énergie basse |
| `wave` | impulsion lancée sur chaque attaque de grave, qui se propage |
| `pulse` | ruban uni, teinte selon le centre spectral |

| réglage | effet |
| --- | --- |
| `--audio-fps` | cadence LED, 25 par défaut |
| `--audio-mode` | rendu au démarrage |
| `--audio-config` | fichier des réglages, relus au lancement et réécrits à chaque changement |
| `POST /bridge/audio` | `{"mode":…, "gain":…, "auto":…, "fps":…, "curve":…, "floor":…}` à chaud |
| `GET /bridge/audio` | images émises, abandonnées, niveau, erreur |

Une notification met l'audio en pause le temps du flash, puis le relance. Tant que l'audio
diffuse, elle est peinte dans le flux temps réel lui-même — voir
[Notifications pendant le son réactif](#notifications-pendant-le-son-réactif).

### Adalight plutôt que TPM2

Les deux fonctionnent, mais le compteur TPM2 de WLED divise chaque octet de longueur
séparément : `(0x01×256)/3 + 0xB0/3` donne 143 au lieu de 144. **La dernière LED reste
éteinte.** Mesuré sur le module : 143/144 en TPM2, 144/144 en Adalight, dont le compteur
est exact. Le pont envoie donc de l'Adalight.

### Débit et désynchronisation

Mesuré sur ce module, trame de 438 octets : **26,5 images/s à 115 200 bauds**, et
**236 à 921 600** après un `0xB5`. Le ruban se rafraîchit à 43 images/s au repos, donc
115 200 suffit largement et reste le défaut.

En flux à 25 images/s, la cadence du ruban retombe mesurément à 17 images/s : à 115 200
une trame met 38 ms à passer, et l'ESP32 partage ce temps avec son propre affichage.
C'est fluide à l'œil, mais c'est le plafond réel de ce débit.

> [!WARNING]
> Changer de débit en plein flux est dangereux. WLED lit `0xB0`–`0xB7` comme des
> commandes dès que son automate est entre deux trames ; après une désynchronisation,
> un simple octet de pixel vaut une commande. C'est arrivé pendant les essais : le
> module s'est retrouvé à 460 800 sans qu'on le lui demande. Si ça vous arrive,
> débrancher et rebrancher le module le ramène à sa valeur configurée.

## Streaming audio-réactif (LedFx, Adalight)

Le même handler série accepte aussi **Adalight** et **TPM2**. Un logiciel comme LedFx
peut donc piloter le module en USB avec un device de type *Adalight* (115200 bauds, votre
nombre de LEDs). Les effets sont alors calculés sur l'ordinateur, contrairement au pont
qui
pilote les effets internes de WLED.

Un seul programme à la fois peut ouvrir le port : arrêtez le pont avant de lancer LedFx.
Le verrou exclusif fait que l'un des deux refusera de démarrer plutôt que de corrompre
la liaison de l'autre.

## Notifications

Le bandeau sert d'indicateur : à l'arrivée d'une notification, il interrompt la scène
en cours, joue un motif coloré, puis **restaure exactement l'état précédent**
(alimentation, luminosité, effet, palette, bornes de segment, couleurs).

### Notifications pendant le son réactif

Les trames Adalight basculent WLED en **mode temps réel** : il ignore ses propres effets et
affiche les pixels reçus, et il y reste 2,5 secondes après la dernière trame, valeur par
défaut du firmware. Une notification envoyée comme changement d'état JSON pendant cette
fenêtre ne change donc rien
sur le bandeau : le module affiche toujours la dernière image audio.

Aussi, quand une trame temps réel est partie il y a moins de deux secondes, la notification
est dessinée *dans* le flux : l'audio se met en pause, les flashs partent en trames
Adalight, puis l'audio reprend et repeint. Aucun état n'est touché, il n'y a donc rien à
restaurer.

Une conséquence : les pixels temps réel sont mis à l'échelle par la luminosité courante du
bandeau, que le pont ne peut pas remplacer le temps d'un flash. Le motif est donc peint à
pleine échelle, plafonné par le budget de courant, plutôt qu'à son propre `bri` — ainsi une
notification n'est jamais plus terne que le son qu'elle interrompt.

### N'importe quoi, par HTTP

La voie générale, c'est un seul endpoint : tout ce qui sait faire une requête HTTP peut
allumer le bandeau — un job de CI, une cron, un Makefile, un Stream Deck :

```bash
curl -X POST http://127.0.0.1:8723/bridge/notify \
     -H 'Content-Type: application/json' \
     -d '{"app":"Jenkins","title":"deploy terminé","pattern":"info"}'
```

`notify.sh` l'enrobe pour le shell, et `WLED_USB_URL` change l'adresse visée :

```bash
./notify.sh CI "build cassé" urgent
./notify.sh Slack "nouveau message"
make test || ./notify.sh Tests "échec" urgent
```

### Optionnel : les notifications du téléphone via KDE Connect

Désactivé par défaut, et utile seulement si vous utilisez déjà KDE Connect. Activation
avec `--kdeconnect`.

Les notifications relayées par KDE Connect sont lues sur la session D-Bus privée que son
application de bureau lance pour elle-même. Le pont la trouve tout seul en sondant les
emplacements habituels (`/tmp/dbus-*`, `/run/user/*/bus`) à la recherche du nom
`org.kde.kdeconnect`, puis interroge `activeNotifications` toutes les 2 secondes et réagit
aux nouvelles entrées. `--kdeconnect-bus` impose une adresse explicite, et
`DBUS_SESSION_BUS_ADDRESS` est honorée si elle est définie.

Il ne lit que `appName` et `title`. **Le corps des messages n'est jamais lu, ni journalisé,
ni envoyé nulle part.** Le journal reste en mémoire : il disparaît à l'arrêt du pont.

Prérequis : `gdbus` — `brew install glib` sur macOS, souvent déjà là sous Linux — et KDE
Connect appairé au téléphone. L'app de la barre des tâches le laisse éteint sauf demande :

```bash
defaults write fr.wledusb.app kdeconnect -bool true
```

### Motifs et règles

Réglables dans la page `/bridge`, stockés dans `data/notifications.json`. Un motif
définit une couleur, un nombre de LEDs, une luminosité et un nombre de flashs ; une
règle associe le nom d'une application à un motif. Sans règle correspondante, le motif
`defaultPattern` s'applique.

Les notifications identiques reçues dans la fenêtre `coalesceSeconds` sont groupées,
et `quietHours` permet de museler le bandeau sur une plage horaire.

### Budget de courant

**À lire si vos LEDs sont alimentées par le microcontrôleur.** Le limiteur de courant
de WLED (*Automatic Brightness Limiter*) vaut 2000 mA par défaut, bien au-delà de ce
qu'un port USB fournit. Demander plus que ce que l'alimentation peut donner fait chuter
la tension et **le module redémarre** — rien à voir avec les notifications, toute scène
vive en plein bandeau le provoque.

Calculez votre propre plafond plutôt que de reprendre les chiffres d'un autre. En ordre
de grandeur, une LED RVB tire jusqu'à environ 55 mA en blanc plein, le contrôleur lui-même
consomme autour de 100 mA au repos, et la consommation suit la luminosité et le nombre de
canaux qu'allume la couleur. Un port USB à 500 mA est donc à court bien avant qu'un long
bandeau atteigne sa pleine luminosité.

Les chiffres ci-dessous viennent d'**une seule** installation — un bandeau de 144 LEDs
WS2812B alimenté en USB — et montrent l'allure de la courbe, ils ne sont pas à réutiliser :

| Scène | Conso estimée par WLED |
| --- | --- |
| 20 LEDs @ bri 140 | 389 mA |
| 40 LEDs @ bri 140 | 659 mA |
| 144 LEDs @ bri 30 | 536 mA |
| 144 LEDs @ bri 60 | 952 mA |
| 144 LEDs @ bri 160, couleur vive | coupure |

Deux protections :

1. Régler le limiteur du module (*Maximum Current*) sur une valeur réaliste — 400 à
   500 mA pour une alimentation USB. Ce réglage n'est **pas accessible par le port
   série** : il faut passer une fois par le serveur web du module, par exemple en se
   connectant à son point d'accès (`http://4.3.2.1/settings/leds`).
2. Côté pont, les motifs n'allument qu'une portion du bandeau et leur luminosité est
   réduite automatiquement pour tenir sous `powerBudgetMa`, lui-même plafonné par la
   limite que le module annonce dans `info.leds.maxpwr`. Il vaut 700 mA par défaut, ce qui
   suppose une alimentation USB — relevez-le dans `/bridge` si votre bandeau a sa propre
   alimentation, ainsi que `ledMilliamps` si vos LEDs ne sont pas des RVB ordinaires.

### Pourquoi les notifications du bureau ne peuvent pas être reprises

macOS n'expose aucune API pour lire les notifications d'une autre application : le pont
ne peut donc pas refléter ce qu'affichent vos applications de bureau — messagerie, mail,
outil de build. Ce n'est pas un oubli ; chaque contournement réclame une permission bien
plus large que le besoin :

- la base du Centre de notifications (`group.com.apple.usernoted`) exige un **accès
  disque complet** ;
- lire le badge du Dock d'une application via System Events exige une autorisation
  **Automation**, et renvoie l'erreur `-1743` sans elle ;
- `lsappinfo` ne renvoie plus rien d'exploitable (vérifié sur macOS 27).

D'où le parti pris des déclencheurs ci-dessus : ne surveiller que ce qui est observable
sans rien demander. Quand une application tourne aussi sur un téléphone appairé en KDE
Connect, ses notifications arrivent par ce chemin, avec leur propre `appName` — qu'une
règle peut ensuite associer à un motif.

## Architecture

```
wled_usb/serialport.py  ouverture termios brute (CLOCAL, sans toucher DTR/RTS)
wled_usb/link.py        transactions série, parseur lignes JSON + trames TPM2, reconnexion
wled_usb/bridge.py      cache d'état, polling, diffusion WebSocket, liveview
wled_usb/httpd.py       serveur HTTP + WebSocket, émulation de l'API WLED
wled_usb/flash.py       pilotage d'esptool avec libération du port
wled_usb/presets.py     cache local des presets
wled_usb/data.py        base statique effets/palettes
wled_usb/audio.py       rendus audio-réactifs, gain automatique, émission Adalight
wled_usb/listen.py      résolution des adresses d'écoute (localhost, Tailscale, NetBird)
wled_usb/ui.py          préférence de langue partagée par la page et le menu
wled_usb/ws.py          cadrage WebSocket minimal
wled_usb/notify.py      moteur de notifications : motifs, file, budget, restauration
wled_usb/kdeconnect.py  source KDE Connect optionnelle (découverte du bus, veille D-Bus)
app/Sources/            application macOS : capture audio, FFT, menu, déclencheurs
public/                 pages propres au pont (/bridge, page d'indisponibilité)
vendor/                 interface web WLED redistribuée
tools/gen-data.py       extraction des effets et palettes depuis les sources WLED
notify.sh               déclenchement en ligne de commande
```

Le transport série est volontairement en `termios` brut plutôt qu'en pyserial : pyserial
pilote DTR/RTS à l'ouverture, et toute carte câblée pour l'auto-reset — c'est-à-dire la
plupart de celles qui ont une prise USB — y lit une demande de redémarrage et **redémarre
à chaque connexion du pont**. L'ouverture brute en `CLOCAL` laisse ces lignes
tranquilles.
pyserial reste présent — esptool en dépend.

## Sécurité

**Par défaut le pont n'écoute que sur la boucle locale.** Il ouvre une socket par
adresse demandée, jamais de joker : `0.0.0.0` n'est jamais lié, donc rien n'est joignable
depuis le réseau local même si la machine y est. Le module, lui, n'est sur aucun réseau.

L'absence d'en-têtes CORS ne protège de rien : elle empêche une page tierce de **lire**
la réponse, pas de **poster** la requête. Une page web ouverte dans le navigateur
pouvait donc piloter les LEDs — et surtout atteindre `POST /bridge/flash`, qui écrit un
firmware arbitraire sur le module. Le pont contrôle donc deux en-têtes sur chaque
requête :

| en-tête | contrôle | ce qu'il bloque |
| --- | --- | --- |
| `Host` | doit correspondre à une adresse d'écoute | la réattribution DNS : un domaine hostile qui résout vers `127.0.0.1` |
| `Origin` | s'il est présent, doit être une origine du pont | les requêtes émises par une page tierce, WebSocket compris |

Un `Origin` absent est accepté : c'est le cas de `curl`, de `notify.sh` et des scripts.
Le risque visé est le navigateur, et un navigateur joint toujours `Origin` à une requête
d'origine croisée.

### Optionnel : joindre le pont depuis une autre machine

Tout ce qui suit est facultatif et désactivé tant que vous ne le demandez pas.
`--listen` prend une liste séparée par des virgules, mêlant adresses littérales et
mots-clés :

```bash
./run.sh --listen localhost,192.168.1.42   # une adresse littérale
./run.sh --listen localhost,tailscale      # l'adresse que Tailscale donne à cette machine
```

| mot-clé | résolution |
| --- | --- |
| `localhost` | `127.0.0.1` |
| `tailscale` | sortie de `tailscale ip` (IPv4 et IPv6) |
| `netbird` | lignes `NetBird IP` / `NetBird IPv6` de `netbird status` |

Les deux mots-clés de réseau maillé existent parce qu'un maillage privé est à peu près
la seule façon saine d'exposer un service sans authentification. Ce sont des commodités,
pas des prérequis : les adresses sont résolues au démarrage en lançant le client, jamais
écrites en dur, puisqu'elles changent avec le réseau. Un mot-clé dont le client n'est pas
installé ou pas connecté est signalé puis ignoré, une adresse déjà prise n'empêche pas les
autres de s'ouvrir, et le pont ne refuse de démarrer que s'il ne reste aucune adresse.

L'app de la barre des tâches passe `localhost` sauf indication contraire :

```bash
defaults write fr.wledusb.app listen "localhost,tailscale"
```

Un avertissement s'affiche si une adresse liée se trouve être routable publiquement. Les
plages de Tailscale (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`) et de NetBird ne le sont pas.

> [!CAUTION]
> **Le pont n'a aucune authentification.** Tout ce qui atteint le port peut piloter
> les LEDs et flasher le firmware. Sur un réseau maillé, cela vaut pour chaque pair,
> et pour tout appareil avec qui la machine est partagée.

## Comment ce projet a été écrit

Une bonne partie de ce code a été écrite avec un assistant IA (Claude Code), avec un
humain qui possède le matériel et a tout fait tourner dessus. Autant le dire clairement
plutôt que de vous laisser le deviner.

Deux conséquences, qui vont dans les deux sens :

- Les chiffres de ce README ont été **mesurés**, pas supposés — cadences, consommation,
  le décalage d'une LED du compteur TPM2, la désynchronisation de débit. Chacun vient
  d'un essai sur le module et de ce qu'il a répondu. Là où rien n'a été mesuré, le texte
  le dit.
- Une seule paire d'yeux a relu l'ensemble. Lisez le code avant de lui confier votre
  matériel, comme pour n'importe quel petit projet.

## Licence et crédits

Le projet est publié sous **EUPL v. 1.2 ou ultérieure**. Voir `LICENSE` pour le texte,
et `NOTICE` pour le détail des composants tiers qu'il redistribue : l'interface web de
WLED (EUPL-1.2), iro.js (MPL-2.0) et rangetouch.js (MIT).

Les binaires de firmware ne sont pas versionnés. `firmware/*.bin` est exclu par
`.gitignore` ; récupérer la version voulue sur la
[page des releases WLED](https://github.com/wled/WLED/releases) et vérifier son
empreinte avant de flasher :

```bash
shasum -a 256 firmware/WLED_16.0.1_ESP32.bin
# 628917b0753edcfc9a8408e6387c6d1ace6a360d315441e9563d60299fef8594
```

<sub>made with ❤️ by Matthieu Jeannin 🇫🇷</sub>
