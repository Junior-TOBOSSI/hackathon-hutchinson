"""
Prépare les 5 plis de validation croisée avec 3 classes :
    OK          : exactement 1 joint dans la gorge
    NOK_SANS    : aucun joint
    NOK_DOUBLE  : 2 joints ou plus
(règle Hutchinson : NOK = aucun joint OU plus d'un joint)

Le type de chaque rafale NOK vient du fichier de tri rempli à la main (tri_nok.csv,
produit par planches_tri.py). Les rafales sont les mêmes que d'habitude (pause > 3 s).

Les rafales de CHAQUE TYPE sont réparties dans les 5 plis, pour que chaque pli
contienne si possible les 3 types en val et en test.

Avec --binaire, le script écrit les MÊMES plis mais avec seulement 2 dossiers (OK / NOK) :
c'est la référence pour comparer honnêtement "2 classes" et "3 classes".

Usage (cluster) :
    python preparer_3classes.py --donnees $HOME/hackathon/donnees/702 \
        --tri $HOME/hackathon/tri/tri_nok.csv --sortie $HOME/hackathon/dataset_702_3c --ecraser
    python preparer_3classes.py ... --sortie $HOME/hackathon/dataset_702_2c --binaire --ecraser

Sortie : <sortie>_pli0 ... <sortie>_pli4, chacun avec train/ val/ test/ et repartition.csv
"""
import argparse
import csv
import shutil
from pathlib import Path

from preparer_donnees_rafales import lister_images, SEUIL_RAFALE_S

N_PLIS = 5
TYPES_NOK = {"SANS": "NOK_SANS", "DOUBLE": "NOK_DOUBLE"}


def lire_tri(chemin: Path):
    """Renvoie {rafale: 'SANS' | 'DOUBLE' | 'HORS_CADRE'} à partir du CSV rempli à la main."""
    with open(chemin, encoding="utf-8") as h:
        lignes = list(csv.DictReader(h))
    tri = {}
    for l in lignes:
        t = (l.get("type") or "").strip().upper()
        tri[l["rafale"].strip()] = t
    return tri


def attribuer_plis(images):
    """Répartit les rafales de chaque type en 5 plis de tailles proches (plus grosses d'abord)."""
    pli_de = {}
    for typ in sorted({d["type"] for d in images}):
        tailles = {}
        for d in images:
            if d["type"] == typ:
                tailles[d["rafale"]] = tailles.get(d["rafale"], 0) + 1
        charge_img, charge_raf = [0] * N_PLIS, [0] * N_PLIS
        for r, n in sorted(tailles.items(), key=lambda kv: (-kv[1], kv[0])):
            # d'abord le pli qui a le moins de rafales de ce type, puis le moins d'images
            k = min(range(N_PLIS), key=lambda i: (charge_raf[i], charge_img[i]))
            pli_de[r] = k
            charge_raf[k] += 1
            charge_img[k] += n
    return pli_de


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--donnees", required=True, help="dossier contenant OK/ et NOK/")
    p.add_argument("--tri", required=True, help="tri_nok.csv rempli (colonne type : SANS, DOUBLE ou HORS_CADRE)")
    p.add_argument("--sortie", required=True, help="préfixe des dossiers créés (_pli0 ... _pli4 ajoutés)")
    p.add_argument("--binaire", action="store_true", help="mêmes plis, mais 2 dossiers OK / NOK (référence)")
    p.add_argument("--seuil-rafale", type=float, default=SEUIL_RAFALE_S)
    p.add_argument("--exclure", default=None, help="exclusions.csv produit par nettoyer_donnees.py (photos retirées)")
    p.add_argument("--ecraser", action="store_true")
    args = p.parse_args()

    images = lister_images(Path(args.donnees), args.seuil_rafale)
    # Nettoyage : on retire les photos listées APRÈS le calcul des rafales (numéros inchangés)
    if args.exclure:
        with open(args.exclure, encoding="utf-8") as h:
            a_exclure = {l["fichier"] for l in csv.DictReader(h)}
        avant = len(images)
        nettoyees = [d for d in images if d["chemin"].name in a_exclure]
        images = [d for d in images if d["chemin"].name not in a_exclure]
        print(f"NETTOYAGE ({args.exclure}) : {avant - len(images)} photos retirées, rafales touchées "
              f"{', '.join(sorted({d['rafale'] for d in nettoyees}))}")
    tri = lire_tri(Path(args.tri))

    # Contrôle du tri : chaque rafale NOK doit avoir un type valide
    raf_nok = sorted({d["rafale"] for d in images if d["classe"] == "NOK"})
    manquantes = [r for r in raf_nok if tri.get(r, "") not in ("SANS", "DOUBLE", "HORS_CADRE")]
    if manquantes:
        raise SystemExit("ERREUR : type absent ou invalide pour " + ", ".join(manquantes) +
                         ". Mets SANS, DOUBLE ou HORS_CADRE dans la colonne type de " + args.tri)
    raf_ok_dans_tri = [r for r in tri if r not in raf_nok and tri[r]]
    if raf_ok_dans_tri:
        print("Remarque : rafales hors NOK présentes dans le tri, ignorées :", ", ".join(raf_ok_dans_tri))

    exclues = [d for d in images if d["classe"] == "NOK" and tri[d["rafale"]] == "HORS_CADRE"]
    images = [d for d in images if d not in exclues]
    for d in images:
        d["type"] = "OK" if d["classe"] == "OK" else TYPES_NOK[tri[d["rafale"]]]
        d["dossier"] = d["classe"] if args.binaire else d["type"]

    pli_de = attribuer_plis(images)
    print(f"Rafales par type : " + ", ".join(
        f"{t} {len({d['rafale'] for d in images if d['type'] == t})}" for t in ["OK", "NOK_SANS", "NOK_DOUBLE"]))
    if exclues:
        print(f"EXCLUES (HORS_CADRE, à signaler dans le rapport et au jury) : "
              f"{len(exclues)} images, rafales {', '.join(sorted({d['rafale'] for d in exclues}))}")

    probleme = False
    for k in range(N_PLIS):
        k_test, k_val = k, (k + 1) % N_PLIS
        sortie = Path(f"{args.sortie}_pli{k}")
        if sortie.exists() and any(sortie.iterdir()):
            if not args.ecraser:
                raise SystemExit(f"{sortie} n'est pas vide : relance avec --ecraser.")
            if not (sortie / "repartition.csv").exists():
                raise SystemExit(f"{sortie} ne ressemble pas à un découpage de ce script : je ne supprime rien.")
            shutil.rmtree(sortie)
        for d in images:
            pli = pli_de[d["rafale"]]
            d["pli"] = pli
            d["split"] = "test" if pli == k_test else "val" if pli == k_val else "train"
            dest = sortie / d["split"] / d["dossier"]
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(d["chemin"], dest / d["chemin"].name)
        with open(sortie / "repartition.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["fichier", "classe", "type", "rafale", "pli", "split"])
            for d in images:
                w.writerow([d["chemin"].name, d["classe"], d["type"], d["rafale"], d["pli"], d["split"]])

        print(f"\nPli {k} (test = pli {k_test}, val = pli {k_val}) -> {sortie}")
        dossiers = sorted({d["dossier"] for d in images})
        for split in ["train", "val", "test"]:
            morceaux = []
            for cl in dossiers:
                sel = [d for d in images if d["split"] == split and d["dossier"] == cl]
                morceaux.append(f"{cl} {len(sel):3d} img / {len({d['rafale'] for d in sel})} raf")
                if split in ("val", "test") and not sel:
                    probleme = True
                    print(f"  ALERTE : {split} sans aucune image {cl}.")
            print(f"  {split:5s} : " + " | ".join(morceaux))
    if probleme:
        print("\nALERTE : au moins un pli a un bloc val ou test incomplet. Un val incomplet empêche "
              "l'entraînement de ce pli (le script d'entraînement s'arrêtera avec un message clair).")


if __name__ == "__main__":
    main()
