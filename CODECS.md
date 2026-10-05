# Recommandations d'encodage (Performances Vidéo)

Pour des performances maximales lors de l'utilisation de l'installation, il est crucial de soulager le processus de décodage. L'objectif est d'avoir le **délai de seek (saut) le plus faible possible** et d'éviter les surcharges CPU/GPU lors de la lecture simultanée de plusieurs vidéos ou des sauts rapides générés par le contrôleur MIDI.

Pour cela, le secret est d'utiliser un codec **Intra-frame** (chaque image est autonome et ne dépend pas de la précédente).

## 1. La solution Ultime : Apple ProRes 422
C'est le format idéal pour du live, du VJing ou des installations interactives. Le décodage est instantané, surtout sur macOS.
**Inconvénient :** La taille des fichiers est très importante.

### ProRes 422 Proxy (Recommandé pour gagner de la place)
```bash
ffmpeg -i input.mp4 -c:v prores_ks -profile:v 0 -c:a pcm_s16le output.mov
```

### ProRes 422 LT (Un peu plus de qualité)
```bash
ffmpeg -i input.mp4 -c:v prores_ks -profile:v 1 -c:a pcm_s16le output.mov
```

---

## 2. Le meilleur compromis : H.264 ALL-Intra
Si le stockage est un problème et que le ProRes prend trop de place, tu peux forcer le codec H.264 à se comporter de manière similaire en supprimant les dépendances entre les images (GOP de 1). 
L'utilisation de `h264_videotoolbox` permet en plus de tirer parti de l'accélération matérielle des puces Apple Silicon / Intel.

```bash
# -g 1 force l'encodeur à créer une image-clé pour chaque frame
# -b:v 8M ajuste le bitrate (à adapter selon tes besoins de qualité)
ffmpeg -i input.mp4 -c:v h264_videotoolbox -g 1 -b:v 8M -c:a aac output.mp4
```

---

## 3. Astuces supplémentaires
* **Audio :** Préfère les formats audio non compressés (`pcm_s16le` par exemple, qui équivaut au WAV) ou à très faible latence si tu as des problèmes de synchronisation.
* **Résolution :** Ne garde pas les vidéos en 4K si ton projecteur/écran est en 1080p. Réduire la résolution à la source accélère grandement le décodage (`-vf scale=1920:1080`).
