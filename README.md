# EZO Complete — Home Assistant

Intégration HACS pour les sticks USB **Atlas Scientific EZO Complete** :

- **EZO Complete-ORP** (redox, mV)
- **EZO Complete-pH** (pH, cal 1/2/3 points, compensation température)

Un dongle USB = une entrée. Le type est lu via `i` (`?i,ORP,…` / `?i,pH,…`).  
Remplace [echavet/ezo-orp](https://github.com/echavet/ezo-orp) (gelé).

Home Assistant **2026.5+** (`serialx`).

L’icône s’affiche dans **Paramètres → Appareils et services** (`brand/` local, HA 2026.3+). Dans **HACS**, « Icon not available » est un [bug HACS connu](https://github.com/hacs/integration/issues/5223) : HACS interroge encore `brands.home-assistant.io` au lieu du brand local. L’`icon.png` à la racine du dépôt est bien fourni.

## Installation (HACS)

1. HACS → Custom repositories → `https://github.com/echavet/ezo-complete` → Integration
2. Download **EZO Complete** → redémarrer HA
3. Brancher le stick USB → découverte, ou *Ajouter une intégration*

Deux sticks (pH + ORP) : deux entrées, unique ID `{serial_ftdi}_ph` / `{serial_ftdi}_orp`.

## pH — compensation température

Options de l’entrée pH → **Sonde de température**. Choisir une entité HA `sensor` (device class temperature, ex. sonde bassin Vigipool).  
L’intégration envoie `T,<celsius>` au circuit. Sans entité, la puce reste à 25 °C (défaut Atlas, **non conservé** hors tension).

Calibration pH : **mid d’abord** (7.00), puis low (4) et/ou high (10), en regardant le pH live se stabiliser.

## ORP

Calibration 1 point `Cal,<mV>` (bouton 225 mV ou valeur perso). Live obligatoire avant d’envoyer.

## Export / restore

- Archive datée : `/config/ezo_complete/<id>_calibration_YYYYMMDD-HHMMSS.txt`
- Dernière copie : `/config/ezo_complete/<id>.import_calibration`
- Bouton / service **restore_calibration** relit ce fichier

## Licence

MIT. Non affilié à Atlas Scientific.
