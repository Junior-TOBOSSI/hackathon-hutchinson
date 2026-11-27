"""
Inférence du modèle qualité 702 : prétraitement, modèle, post-traitement.

Entrée  : une photo de la caméra qualité (chemin, image OpenCV BGR ou image PIL).
Sortie  : un dictionnaire JSON-compatible (voir exemple_sortie.json).

Prétraitement : fait par Ultralytics, ne rien redimensionner soi-même.
    Ultralytics (classify_transforms) redimensionne le petit côté à `imgsz`,
    recadre le centre en carré imgsz x imgsz, passe en RGB et divise par 255.
Post-traitement :
    score_nok = somme des probabilités des classes dont le nom commence par "NOK"
    score_nok >= seuil_nok                         -> verdict "NOK"
    seuil_a_verifier <= score_nok < seuil_nok      -> verdict "A_VERIFIER" (si seuil_a_verifier est renseigné)
    sinon                                          -> verdict "OK"
    type_defaut = classe NOK la plus probable (seulement si verdict NOK ou A_VERIFIER)
"""
import time
from pathlib import Path

import numpy as np
import yaml

LIBELLES = {
    "OK": "1 joint dans la gorge : pièce conforme",
    "NOK_SANS": "aucun joint dans la gorge",
    "NOK_DOUBLE": "plus d'un joint dans la gorge",
    "NOK": "pièce non conforme",
}


class Qualite702:
    def __init__(self, config="config_qualite702.yaml", device=None):
        chemin_cfg = Path(config).resolve()
        self.cfg = yaml.safe_load(chemin_cfg.read_text(encoding="utf-8"))
        modele = Path(self.cfg["modele"])
        if not modele.is_absolute():                      # chemin relatif au fichier de config
            modele = chemin_cfg.parent / modele
        if not modele.exists():
            raise FileNotFoundError(f"Poids introuvables : {modele}")

        from ultralytics import YOLO                      # import ici : le module se charge vite
        self.modele = YOLO(str(modele), task="classify")
        self.device = device if device is not None else str(self.cfg.get("device", "cpu"))
        self.imgsz = int(self.cfg["imgsz"])
        self.classes = list(self.cfg["classes"])          # dans l'ordre des indices du modèle

        # Garde-fou : les classes du fichier de config doivent être celles du modèle
        noms_modele = getattr(self.modele, "names", None)
        if isinstance(noms_modele, dict) and noms_modele:
            liste = [noms_modele[k] for k in sorted(noms_modele)]
            if liste != self.classes:
                raise ValueError(f"Classes de la config {self.classes} différentes de celles du modèle {liste}")

        self.idx_nok = [i for i, n in enumerate(self.classes) if n.startswith("NOK")]
        if not self.idx_nok:
            raise ValueError("Aucune classe NOK dans la config")
        self.seuil = float(self.cfg["seuil_nok"])
        sav = self.cfg.get("seuil_a_verifier")
        self.seuil_av = float(sav) if sav not in (None, "", "null") else None
        self.info_modele = {"nom": self.cfg.get("nom", "qualite702"), "version": str(self.cfg.get("version", "?")),
                            "fichier": modele.name}

    # ------------------------------------------------------------------ cœur
    def probabilites(self, image):
        """Renvoie le vecteur de probabilités (une valeur par classe, somme = 1)."""
        r = self.modele.predict(image, imgsz=self.imgsz, device=self.device, verbose=False)[0]
        return np.asarray(r.probs.data.cpu().numpy(), dtype=float)

    def interpreter(self, p):
        """Post-traitement : probabilités -> verdict métier."""
        score = float(p[self.idx_nok].sum())
        if score >= self.seuil:
            verdict = "NOK"
        elif self.seuil_av is not None and score >= self.seuil_av:
            verdict = "A_VERIFIER"
        else:
            verdict = "OK"
        type_defaut = None
        if verdict != "OK":
            type_defaut = self.classes[max(self.idx_nok, key=lambda i: p[i])]
        libelle = LIBELLES.get(type_defaut or "OK", type_defaut)
        if verdict == "A_VERIFIER":
            libelle = f"doute : à vérifier par l'opérateur (piste : {libelle})"
        return {
            "cas_usage": "qualite",
            "reference": str(self.cfg.get("reference", "702")),
            "verdict": verdict,
            "type_defaut": type_defaut,
            "libelle": libelle,
            "score_nok": round(score, 4),
            "seuil_nok": self.seuil,
            "seuil_a_verifier": self.seuil_av,
            "probabilites": {c: round(float(v), 4) for c, v in zip(self.classes, p)},
            "modele": self.info_modele,
        }

    def predire(self, image):
        """Une photo -> dictionnaire résultat (avec la latence mesurée en ms)."""
        t0 = time.perf_counter()
        p = self.probabilites(image)
        res = self.interpreter(p)
        res["latence_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return res

    def predire_lot(self, images):
        return [self.predire(im) for im in images]

