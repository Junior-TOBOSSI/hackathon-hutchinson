"""
Prépare le dossier d'entraînement YOLO (classification) en découpant PAR RAFALE.

Une rafale = une série de photos prises coup sur coup (pause > seuil = nouvelle rafale).
Seuil par défaut : 3 s. Avec --seuil-rafale 10, les fragments proches sont regroupés (test plus sévère).
Chaque rafale entière va dans UN SEUL des trois blocs (train, val ou test) :
le modèle est donc testé sur des pièces qu'il n'a jamais vues.

Les rafales de chaque classe sont réparties en 5 "plis" (paquets) équilibrés.
Par défaut : pli 0 = test, pli 1 = val, plis 2 à 4 = train.
Avec --pli k : pli k = test, pli k+1 = val (pour la validation croisée).

Usage :
    python preparer_donnees_rafales.py --donnees C:\\Sources\\ServiceIa\\hackhaton\\donnees_hutchinson\\702 ^
                                       --sortie C:\\hackathon\\dataset_702_rafales
    python preparer_donnees_rafales.py ... --pli 1 --ecraser                  # autre découpage
    python preparer_donnees_rafales.py ... --pli 1 --seuil-rafale 10 --ecraser  # groupes plus larges

Sortie (format attendu par YOLO classification) :
    sortie/train/OK, sortie/train/NOK, sortie/val/..., sortie/test/..., sortie/repartition.csv
"""
import argparse
import csv
import shutil
from pathlib import Path

SEUIL_RAFALE_S = 3.0
N_PLIS = 5


def lister_images(racine: Path, seuil_s: float = SEUIL_RAFALE_S):
    images = []
    for classe in ["OK", "NOK"]:
        for chemin in (racine / classe).glob("*.jpg"):
            epoch_ms = int(chemin.stem.split("_")[-1])   # S6000702_<epoch ms>.jpg
            images.append({"chemin": chemin, "classe": classe, "epoch_ms": epoch_ms})
    if not images:
        raise SystemExit(f"ERREUR : aucune image dans {racine}/OK ni {racine}/NOK")
    images.sort(key=lambda d: d["epoch_ms"])           # ordre réel de prise de vue
    rafale, precedent = 0, None
    for d in images:
        # Nouvelle rafale dès que la pause avec la photo précédente dépasse le seuil
        if precedent is not None and (d["epoch_ms"] - precedent) / 1000 > seuil_s:
            rafale += 1
        d["rafale"] = f"R{rafale:02d}"
        precedent = d["epoch_ms"]
    return images


def attribuer_plis(images):
    """Répartit les rafales de chaque classe en 5 plis de tailles proches."""
    pli_de = {}
    for classe in ["OK", "NOK"]:
        tailles = {}
        for d in images:
            if d["classe"] == classe:
                tailles[d["rafale"]] = tailles.get(d["rafale"], 0) + 1
        charge = [0] * N_PLIS
        # Les plus grosses rafales d'abord, chacune dans le pli le moins rempli
        for r, n in sorted(tailles.items(), key=lambda kv: (-kv[1], kv[0])):
            k = charge.index(min(charge))
            pli_de[r] = k
            charge[k] += n
    return pli_de


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--donnees", required=True, help="dossier contenant OK/ et NOK/")
    p.add_argument("--sortie", required=True, help="dossier à créer pour YOLO")
    p.add_argument("--pli", type=int, default=0, help="pli utilisé comme test (0 à 4)")
    p.add_argument("--ecraser", action="store_true", help="remplacer un ancien découpage")
    p.add_argument("--seuil-rafale", type=float, default=SEUIL_RAFALE_S,
                   help="pause (s) au-delà de laquelle on change de groupe (3 par défaut, 10 = groupes plus larges)")
    args = p.parse_args()

    sortie = Path(args.sortie)
    if sortie.exists() and any(sortie.iterdir()):
        # Sécurité : un ancien découpage mélangé au nouveau créerait une fuite
        if not args.ecraser:
            raise SystemExit(f"{sortie} n'est pas vide : relance avec --ecraser pour le remplacer.")
        if not (sortie / "repartition.csv").exists():
            raise SystemExit(f"{sortie} ne ressemble pas à un découpage de ce script : je ne supprime rien.")
        shutil.rmtree(sortie)

    images = lister_images(Path(args.donnees), args.seuil_rafale)
    pli_de = attribuer_plis(images)
    k_test, k_val = args.pli % N_PLIS, (args.pli + 1) % N_PLIS

    for d in images:
        pli = pli_de[d["rafale"]]
        d["pli"] = pli
        d["split"] = "test" if pli == k_test else "val" if pli == k_val else "train"
        dest = sortie / d["split"] / d["classe"]
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(d["chemin"], dest / d["chemin"].name)

    with open(sortie / "repartition.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fichier", "classe", "rafale", "pli", "split"])
        for d in images:
            w.writerow([d["chemin"].name, d["classe"], d["rafale"], d["pli"], d["split"]])

    # Résumé : nombre d'images et de rafales par bloc et par classe
    print(f"Découpage par rafale (pause > {args.seuil_rafale:g} s), pli de test = {k_test}, pli de val = {k_val}")
    for split in ["train", "val", "test"]:
        morceaux = []
        for classe in ["NOK", "OK"]:
            sel = [d for d in images if d["split"] == split and d["classe"] == classe]
            morceaux.append(f"{classe} {len(sel):3d} images / {len({d['rafale'] for d in sel}):2d} rafales")
        print(f"  {split:5s} : " + " | ".join(morceaux))
        # Garde-fou : un bloc val ou test sans l'une des deux classes rend les chiffres inutilisables
        if split != "train" and any(" 0 rafales" in m for m in morceaux):
            print(f"  ALERTE : le bloc {split} ne contient pas les deux classes, ne pas entraîner sur ce pli.")
    print(f"-> {sortie.resolve()}")


if __name__ == "__main__":
    main()
