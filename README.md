# wled-usb — pont USB série pour WLED

Pilote un module WLED **uniquement par USB**, sans aucun accès réseau au module,
et sert l'**interface web officielle de WLED** en local.

Le firmware WLED écoute du JSON sur son port série : tout objet commençant par `{`
est passé à `deserializeState()`, et `{"v":true}` fait répondre l'état complet.
Le pont traduit les requêtes HTTP de l'UI officielle vers ce canal série.

Développé et testé sur WLED 16.0.1, ESP32-PICO-D4, 144 LEDs, macOS 27 sur Apple
Silicon. Le pont lui-même n'a rien de spécifique à macOS ; l'application de barre des
menus décrite plus bas, si.

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
| `--listen localhost,tailscale,netbird` | adresses d'écoute (défaut) |
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

> Après un flash vers une autre version de WLED, régénérez la base statique (ci-dessous),
> sinon les noms d'effets seront décalés. La page `/bridge` signale l'écart.

### Sauvegarde et retour arrière

Avant de reflasher, garder de quoi revenir en arrière : une image intégrale du flash,
l'état du module (`/json`) et la base d'effets de la version en place.

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

Arrêter le pont avant : il garde le port en exclusivité. Le changement de débit après
le stub échoue sur cet adaptateur, rester à 115200.

### Passage de la 0.15.x à la 16.x

Même table de partitions (`WLED_ESP32_4MB_1MB_FS.csv`), donc l'écriture de la seule
application en `0x10000` suffit et la configuration est conservée. La plateforme change
en revanche d'ESP-IDF 3.3 à 4.4.8 : le bootloader en flash reste celui de la 0.15.
Testé ici sur ESP32-PICO-D4, le module démarre correctement.

## Données statiques

`data/wled-data.json` contient les 220 noms d'effets, leurs métadonnées de curseurs,
les 72 noms de palettes et les dégradés d'aperçu. Ces données sont extraites des
sources WLED taguées, pas saisies à la main :

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

`vendor/` contient l'UI officielle WLED 0.15.0, qui pilote sans problème un module en
16.0.1 puisque les listes d'effets et de palettes viennent du pont. Deux modifications :

```
index.js  : "ws://"+window.location.hostname+"/ws"
         →  "ws://"+window.location.host+"/ws"

index.htm : bouton « Pont » ajouté dans la barre du haut, après « Config »
```

L'UI suppose d'être servie sur le port 80 et perdait le port dans l'URL WebSocket.

Le bouton « Pont » ouvre `/bridge` ; la page `/bridge` a son propre lien de retour. Son
icône `⇄` n'appartient pas à la police `WIcons` de WLED, qui ne contient que ses propres
glyphes : `public/skin.css` la repasse donc en police courante. Ce fichier est le point
d'entrée prévu par WLED pour personnaliser le thème, servi tel quel par le pont.

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
| Une app surveillée démarre ou se ferme | `NSWorkspace.did{Launch,Terminate}Application` | `slack` |
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
open "wledusb://notify?pattern=slack&title=Build%20termin%C3%A9&app=CI"
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
| `palette` | rampe de couleurs du rendu : `arc-en-ciel`, `braise`, `océan`, `forêt`, `néon`, `glace`, `coucher`. |
| `floor` (plancher) | lueur de fond appliquée **en sortie**, sur les LEDs que le rendu laisse noires. |
| `auto` (gain automatique) | ajuste le gain tout seul selon le volume de la source. Le curseur `gain` devient alors le taux de remplissage visé aux crêtes. |

Une porte de présence, calée sur le RMS brut, garde le ruban éteint au silence — sans
elle, le plancher allumerait les LEDs en permanence.

La normalisation par bande gomme le **timbre**, pas le **volume** : un podcast et un
morceau masterisé fort n'arrivent pas au même niveau, et il fallait reprendre le curseur
de gain à chaque fois. Le gain automatique ferme cette boucle. Chaque rendu déclare dans
`DRIVES` la grandeur qu'il multiplie par le gain — crête des bandes pour `spectre`,
moyenne des graves pour `graves`, etc. — et le moteur suit cette grandeur avec un
détecteur de crête à attaque rapide (0,3 par image) et relâchement lent (0,01, soit
quelques secondes). Le gain appliqué vaut `gain × (1 / enveloppe)`, borné entre 0,4× et
6×, et affiché en direct sous le curseur.

L'asymétrie attaque/relâchement est ce qui compte : descendre vite évite de saturer sur
un coup de grosse caisse, remonter lentement évite de pomper entre deux couplets. La
boucle est gelée tant que la porte de présence est fermée, sinon le gain partirait au
plafond pendant les silences et le premier son reviendrait en pleine face.

Deux leçons tirées à l'usage. Le plancher a d'abord été appliqué au **niveau**, avant le
rendu : sans effet visible, puisque `spectre` et `graves` encodent l'énergie en longueur
de barre et que 3 % d'une zone font un tiers de LED. Il agit maintenant sur les pixels
noirs en sortie, donc dans tous les rendus.

Et normaliser chaque bande sur son propre maximum supprime le relief entre bandes : le
ruban s'allume uniformément et ne raconte plus rien. `AGC_MIX` garde 35 % du niveau
absolu pour que les graves restent plus forts que les aigus.

| rendu | ce qu'il fait |
| --- | --- |
| `spectre` | six barres en miroir depuis le centre, une par groupe de fréquences |
| `graves` | barre qui grandit depuis le centre selon l'énergie basse |
| `onde` | impulsion lancée sur chaque attaque de grave, qui se propage |
| `pulsation` | ruban uni, teinte selon le centre spectral |

| réglage | effet |
| --- | --- |
| `--audio-fps` | cadence LED, 25 par défaut |
| `--audio-mode` | rendu au démarrage |
| `--audio-config` | fichier des réglages, relus au lancement et réécrits à chaque changement |
| `POST /bridge/audio` | `{"mode":…, "gain":…, "auto":…, "fps":…, "curve":…, "floor":…}` à chaud |
| `GET /bridge/audio` | images émises, abandonnées, niveau, erreur |

Une notification met l'audio en pause le temps du flash, puis le relance.

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

> Changer de débit en plein flux est dangereux. WLED lit `0xB0`–`0xB7` comme des
> commandes dès que son automate est entre deux trames ; après une désynchronisation,
> un simple octet de pixel vaut une commande. C'est arrivé pendant les essais : le
> module s'est retrouvé à 460 800 sans qu'on le lui demande. Si ça vous arrive,
> débrancher et rebrancher le module le ramène à sa valeur configurée.

## Streaming audio-réactif (LedFx, Adalight)

Le même handler série accepte aussi **Adalight** et **TPM2**. Un logiciel comme LedFx
peut donc piloter le module en USB avec un device de type *Adalight* (115200 bauds,
144 LEDs). Les effets sont alors calculés sur l'ordinateur, contrairement au pont qui
pilote les effets internes de WLED.

Un seul programme à la fois peut ouvrir le port : arrêtez le pont avant de lancer LedFx.
Le verrou exclusif fait que l'un des deux refusera de démarrer plutôt que de corrompre
la liaison de l'autre.

## Notifications

Le bandeau sert d'indicateur : à l'arrivée d'une notification, il interrompt la scène
en cours, joue un motif coloré, puis **restaure exactement l'état précédent**
(alimentation, luminosité, effet, palette, bornes de segment, couleurs).

### Sources

**KDE Connect** — les notifications de votre téléphone, relayées par KDE Connect, sont
lues sur le bus D-Bus privé que son application macOS lance pour elle-même. Le pont
découvre le bus tout seul en sondant les sockets `/tmp/dbus-*` à la recherche du nom
`org.kde.kdeconnect`, puis interroge `activeNotifications` toutes les 2 secondes et
réagit aux nouvelles entrées.

Il ne lit que `appName` et `title`. **Le corps des messages n'est jamais lu, ni journalisé,
ni envoyé nulle part.** Le journal reste en mémoire : il disparaît à l'arrêt du pont.

Prérequis : `gdbus` (`brew install glib`) et KDE Connect appairé à l'appareil.
Désactivable avec `--no-kdeconnect`.

**Scripts** — une API HTTP et un script shell, pour déclencher depuis n'importe quoi :

```bash
./notify.sh CI "build cassé" urgent
./notify.sh Slack "nouveau message"
make test || ./notify.sh Tests "échec" urgent
```

```bash
curl -X POST http://127.0.0.1:8723/bridge/notify \
     -H 'Content-Type: application/json' \
     -d '{"app":"Jenkins","title":"deploy terminé","pattern":"info"}'
```

`WLED_USB_URL` change l'adresse visée par `notify.sh`.

### Motifs et règles

Réglables dans la page `/bridge`, stockés dans `data/notifications.json`. Un motif
définit une couleur, un nombre de LEDs, une luminosité et un nombre de flashs ; une
règle associe le nom d'une application à un motif. Sans règle correspondante, le motif
`defaultPattern` s'applique.

Les notifications identiques reçues dans la fenêtre `coalesceSeconds` sont groupées,
et `quietHours` permet de museler le bandeau sur une plage horaire.

### Budget de courant

**À lire si vos LEDs sont alimentées par le microcontrôleur.** Le limiteur de courant
de WLED (*Automatic Brightness Limiter*) vaut 2000 mA par défaut, ce qu'une
alimentation USB ne fournit pas. Allumer les 144 LEDs en couleur vive fait chuter la
tension et **le module redémarre** — ce n'est pas propre aux notifications, toute scène
vive en plein bandeau le provoque.

Relevés sur un bandeau de 144 LEDs alimenté en USB :

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
   limite que le module annonce dans `info.leds.maxpwr`.

### Slack sur le Mac

Non implémenté, et pas par choix. Sans jeton d'API, lire les notifications de
l'application Slack du Mac suppose une permission système :

- la base du Centre de notifications (`group.com.apple.usernoted`) exige un **accès
  disque complet** ;
- lire le badge du Dock via System Events exige une autorisation **Automation**
  (sinon erreur `-1743`) ;
- `lsappinfo` ne renvoie plus rien d'exploitable sur macOS 27.

Si Slack tourne sur le téléphone, ses notifications arrivent par KDE Connect avec
`appName = "Slack"`, et la règle correspondante est déjà en place.

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
wled_usb/ws.py          cadrage WebSocket minimal
wled_usb/notify.py      moteur de notifications : motifs, file, budget, restauration
wled_usb/kdeconnect.py  source KDE Connect (découverte du bus, veille D-Bus)
app/Sources/            application macOS : capture audio, FFT, menu, déclencheurs
public/                 pages propres au pont (/bridge, page d'indisponibilité)
vendor/                 interface web WLED redistribuée
tools/gen-data.py       extraction des effets et palettes depuis les sources WLED
notify.sh               déclenchement en ligne de commande
```

Le transport série est volontairement en `termios` brut plutôt qu'en pyserial :
pyserial pilote DTR/RTS à l'ouverture, ce qui **redémarre le module** à chaque
connexion du pont. L'ouverture brute en `CLOCAL` laisse ces lignes tranquilles.
pyserial reste présent — esptool en dépend.

## Sécurité

Le pont ouvre une socket par adresse demandée, jamais de joker : `0.0.0.0` n'est
pas lié, donc rien n'est joignable depuis le réseau local même si la machine y est.
Le module, lui, n'est sur aucun réseau.

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

`--listen` prend une liste séparée par des virgules, mêlant adresses littérales et
mots-clés :

| mot-clé | résolution |
| --- | --- |
| `localhost` | `127.0.0.1` |
| `tailscale` | sortie de `tailscale ip` (IPv4 et IPv6) |
| `netbird` | lignes `NetBird IP` / `NetBird IPv6` de `netbird status` |

Les adresses sont résolues au démarrage, jamais écrites en dur : elles changent avec
le réseau maillé. Un mot-clé dont le client n'est pas installé ou pas connecté est
signalé puis ignoré, et une adresse déjà prise n'empêche pas les autres de s'ouvrir.
Le pont refuse de démarrer seulement si aucune adresse ne reste.

Un avertissement s'affiche si une adresse liée est routable publiquement. Les plages
de Tailscale (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`) et de NetBird ne le sont pas.

> **Le pont n'a aucune authentification.** Tout ce qui atteint le port peut piloter
> les LEDs et flasher le firmware. Sur un réseau maillé, cela vaut pour chaque pair,
> et pour tout appareil avec qui la machine est partagée.

## Licence et crédits

Le projet est sous **EUPL v. 1.2 ou ultérieure**, comme WLED, puisqu'il redistribue
l'interface web de WLED et des données extraites de ses sources. Voir `LICENSE` pour
le texte et `NOTICE` pour le détail des composants tiers : UI WLED (EUPL-1.2),
iro.js (MPL-2.0), rangetouch.js (MIT).

Les binaires de firmware ne sont pas versionnés. `firmware/*.bin` est exclu par
`.gitignore` ; récupérer la version voulue sur la
[page des releases WLED](https://github.com/wled/WLED/releases) et vérifier son
empreinte avant de flasher :

```bash
shasum -a 256 firmware/WLED_16.0.1_ESP32.bin
# 628917b0753edcfc9a8408e6387c6d1ace6a360d315441e9563d60299fef8594
```
