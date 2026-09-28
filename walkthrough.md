# Résumé de l'implémentation : TYG Archives

Le projet a été initialisé avec succès dans `/Users/jminguely/Dev/tyg-archives`.

## Changements effectués
- **Environnement virtuel** : Création d'un `venv` local et installation des paquets requis (`PyQt5`, `python-vlc`, `mido`, `python-rtmidi`).
- **Core Engine** (`core/player_engine.py`) : Implémentation du lecteur VLC avec **3 couches vidéos** superposées. La taille initiale et la position de chaque vidéo déclenchée sont **randomisées** (échelle entre 30% et 70% de l'écran). Le système remplace automatiquement la couche la plus ancienne (Round-Robin).
- **Gestionnaire de Librairie** (`core/library.py`) : Script pour scanner un dossier structuré (`/Année/Type/Media`), détecter le type de fichier, et assigner automatiquement les notes MIDI à la chaîne (ex: C1, C#1...) pour chaque année.
- **Interface Utilisateur** (`ui/`) :
  - `settings.py` : Page des paramètres pour sélectionner l'entrée MIDI et une fonction "Learn" pour assigner les potentiomètres (CC) à la taille et aux positions X/Y.
  - `prep_mode.py` : Interface de préparation pour générer la librairie `config.json`.
  - `install_mode.py` : Interface d'exposition plein écran pour sélectionner l'année, puis écouter le clavier MIDI.
  - `main.py` : Menu principal reliant toutes les interfaces.

## Comment lancer le projet
Ouvrez votre terminal et exécutez ces commandes :

```bash
cd /Users/jminguely/Dev/tyg-archives
source venv/bin/activate
python main.py
```

## Validation (Test à faire)
1. Ouvrez les **Paramètres**, sélectionnez votre clavier MX1000 dans la liste, et utilisez les boutons **Learn CC** pour assigner 3 de vos potentiomètres.
2. Allez dans le **Mode Préparation**, cliquez sur "Scanner un dossier..." (créez un dossier de test avec 2-3 vidéos classées dans un sous-dossier nommé "2012" par exemple), puis cliquez sur "Auto-Assigner MIDI".
3. Allez dans le **Mode Installation**, sélectionnez l'année, et appuyez sur vos touches pour lancer les vidéos de manière aléatoire sur l'écran. Tournez le potentiomètre pour voir la vidéo active changer de taille !
