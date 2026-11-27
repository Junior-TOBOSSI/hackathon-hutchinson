"""
Entraîne une VERSION du modèle qualité 702 prête à intégrer, et écrit :
    <sortie>/modele.pt                 poids entraînés
    <sortie>/config_qualite702.yaml    tout ce qu'il faut pour l'inférence (classes, seuil, imgsz, versions)
    <sortie>/rapport_entrainement.md   rapport détaillé (données, époques, seuil, alertes)
    <sortie>/entrainement/             dossier brut d'Ultralytics (courbes, results.csv)

Données : un dossier préparé par preparer_3classes.py (train/ val/ test/ avec OK, NOK_SANS, NOK_DOUBLE).
Avec --fusionner-test, les images de test sont ajoutées à l'entraînement : c'est ce qu'on fait pour le
modèle livré, car ses performances ont déjà été mesurées par la validation croisée (5 plis).
val reste à part : il sert à choisir l'époque et le seuil.

Usage (cluster) :
    python train.py --dataset $HOME/hackathon/dataset_702_3c_pli1 --fusionner-test \
        --sortie $HOME/hackathon/modeles/qualite702_v1 --version v1 --device 0
"""
import argparse
import csv
import datetime as dt
import os
import platform
import shutil
import time
from pathlib import Path

import numpy as np
import yaml


def choisir_seuil(y, s, vise):
    """Même règle que la validation croisée : 1) rappel >= vise ; 2) le moins de faux rejets ;
    3) le plus de rappel ; puis milieu de la plage de seuils restants."""
    grille = np.linspace(0, 1, 1001)
    rappel = np.array([(s[y == 1] >= t).mean() for t in grille])
    fp = np.array([(s[y == 0] >= t).mean() for t in grille])
    ok = rappel >= vise
    if not ok.any():
        return 0.0, False
    ok &= fp == fp[ok].min()
    ok &= rappel == rappel[ok].max()
    return float(np.median(grille[ok])), True


def classes_du_bloc(d: Path):
    return sorted(x.name for x in d.iterdir() if x.is_dir() and any(x.glob("*.jpg")))


def lire_repartition(dataset: Path):
    f = dataset / "repartition.csv"
    if not f.exists():
        return {}
    with open(f, encoding="utf-8") as h:
        return {r["fichier"]: r for r in csv.DictReader(h)}


def lier(src: Path, dst: Path):
    """Lien symbolique (Linux) ou copie (Windows sans droits)."""
    try:
        os.symlink(src.resolve(), dst)
    except OSError:
        shutil.copy2(src, dst)


def preparer_donnees(dataset: Path, cible: Path, fusionner: bool):
    """Construit le dossier réellement donné à Ultralytics : train (+ test si fusion) et val."""
    if cible.exists():
        shutil.rmtree(cible)
    blocs = {"train": ["train"] + (["test"] if fusionner and (dataset / "test").exists() else []), "val": ["val"]}
    compte = {}
    for bloc, sources in blocs.items():
        for src in sources:
            for d in (dataset / src).iterdir():
                if not d.is_dir():
                    continue
                (cible / bloc / d.name).mkdir(parents=True, exist_ok=True)
                for f in d.glob("*.jpg"):
                    lier(f, cible / bloc / d.name / f.name)
                    compte[(bloc, d.name)] = compte.get((bloc, d.name), 0) + 1
    return compte


def lire_results(run_dir: Path):
    f = run_dir / "results.csv"
    if not f.exists():
        return []
    with open(f, encoding="utf-8") as h:
        lignes = list(csv.DictReader(h))
    out = []
    for l in lignes:
        l = {k.strip(): v for k, v in l.items()}
        acc = next((v for k, v in l.items() if "accuracy_top1" in k), None)
        vl = next((v for k, v in l.items() if k.startswith("val") and "loss" in k), None)
        tl = next((v for k, v in l.items() if k.startswith("train") and "loss" in k), None)
        out.append({"epoch": int(float(l.get("epoch", 0))), "acc": float(acc) if acc else float("nan"),
                    "val_loss": float(vl) if vl else float("nan"), "train_loss": float(tl) if tl else float("nan")})
    return out


def pct(x):
    return "n/a" if x != x else f"{100 * x:.0f} %"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", required=True, help="dossier préparé (train/ val/ test/)")
    p.add_argument("--sortie", required=True, help="dossier de la version, ex. ~/hackathon/modeles/qualite702_v1")
    p.add_argument("--version", required=True, help="nom de version, ex. v1")
    p.add_argument("--hyperparametres", default=str(Path(__file__).with_name("hyperparametres.yaml")))
    p.add_argument("--fusionner-test", action="store_true", help="ajoute test à l'entraînement (modèle livré)")
    p.add_argument("--seuil", type=float, default=None, help="impose le seuil au lieu de le choisir sur val")
    p.add_argument("--device", default="0", help="0 = premier GPU, cpu = processeur")
    p.add_argument("--ecraser", action="store_true", help="autorise à remplacer une version existante")
    args = p.parse_args()

    dataset, sortie = Path(args.dataset).expanduser(), Path(args.sortie).expanduser()
    hp = yaml.safe_load(Path(args.hyperparametres).read_text(encoding="utf-8"))
    if sortie.exists() and any(sortie.iterdir()):
        if not args.ecraser:
            raise SystemExit(f"ERREUR : {sortie} existe déjà. Choisis un autre nom de version ou ajoute --ecraser.")
        shutil.rmtree(sortie)
    sortie.mkdir(parents=True)

    # 1. Données
    cl_train, cl_val = classes_du_bloc(dataset / "train"), classes_du_bloc(dataset / "val")
    if cl_train != cl_val:
        raise SystemExit(f"ERREUR : classes train {cl_train} différentes de val {cl_val}.")
    donnees = sortie / "_donnees"
    compte = preparer_donnees(dataset, donnees, args.fusionner_test)
    repart = lire_repartition(dataset)
    rafales = {}
    for bloc in ["train", "val"]:
        noms = [f.name for f in (donnees / bloc).rglob("*.jpg")]
        rafales[bloc] = sorted({repart.get(n, {}).get("rafale", "?") for n in noms})

    # 2. Entraînement
    import torch
    import ultralytics
    from ultralytics import YOLO
    cles_train = ["epochs", "patience", "imgsz", "batch", "seed", "erasing", "flipud", "hsv_v", "scale"]
    t0 = time.perf_counter()
    modele = YOLO(hp["modele_base"])
    modele.train(data=str(donnees), project=str(sortie), name="entrainement", exist_ok=True,
                 device=args.device, **{k: hp[k] for k in cles_train if k in hp})
    duree = time.perf_counter() - t0
    run_dir = Path(modele.trainer.save_dir)
    shutil.copy2(run_dir / "weights" / "best.pt", sortie / "modele.pt")
    hist = lire_results(run_dir)

    # 3. Seuil choisi sur val (mêmes règles que la validation croisée)
    m = YOLO(str(sortie / "modele.pt"))
    noms = m.names
    classes = [noms[k] for k in sorted(noms)]
    idx_nok = [i for i, c in enumerate(classes) if c.startswith("NOK")]
    items = [(f, 0 if d.name == "OK" else 1, d.name) for d in sorted((donnees / "val").iterdir()) if d.is_dir()
             for f in sorted(d.glob("*.jpg"))]
    res = m.predict([str(f) for f, _, _ in items], imgsz=hp["imgsz"], device=args.device, verbose=False, stream=True)
    probas = [np.asarray(r.probs.data.cpu().numpy(), dtype=float) for r in res]
    y = np.array([t for _, t, _ in items])
    s = np.array([pr[idx_nok].sum() for pr in probas])
    if args.seuil is not None:
        seuil, atteint, origine = args.seuil, True, "imposé par --seuil"
    else:
        seuil, atteint = choisir_seuil(y, s, hp["rappel_vise"])
        origine = "choisi sur val (règle de la validation croisée)"
    pred = s >= seuil
    rappel_val = pred[y == 1].mean() if (y == 1).any() else float("nan")
    fr_val = pred[y == 0].mean() if (y == 0).any() else float("nan")

    # 4. Fichier de configuration d'inférence
    config = {
        "nom": "qualite702", "reference": "702", "version": args.version,
        "date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "modele": "modele.pt", "imgsz": int(hp["imgsz"]), "classes": classes,
        "seuil_nok": round(float(seuil), 4), "seuil_a_verifier": None, "device": "cpu",
        "rappel_vise": hp["rappel_vise"],
        "pretraitement": f"Ultralytics classify : petit côté redimensionné à {hp['imgsz']}, recadrage central "
                         f"{hp['imgsz']}x{hp['imgsz']}, RGB, valeurs / 255",
        "post_traitement": "score_nok = somme des probabilités NOK* ; NOK si score_nok >= seuil_nok",
        "entrainement": {"dataset": str(dataset), "test_fusionne": args.fusionner_test,
                         "rafales_val": rafales["val"], "hyperparametres": hp, "duree_s": round(duree)},
        "versions": {"ultralytics": str(ultralytics.__version__), "torch": str(torch.__version__),
                     "python": platform.python_version()},
    }
    with open(sortie / "config_qualite702.yaml", "w", encoding="utf-8") as h:
        yaml.safe_dump(config, h, allow_unicode=True, sort_keys=False)

    # 5. Rapport détaillé
    alertes = []
    if not atteint:
        alertes.append(f"aucun seuil n'atteint {hp['rappel_vise']:.0%} de rappel sur val : seuil mis à 0, "
                       "tout serait rejeté. Imposer un seuil avec --seuil (ex. médiane des seuils de la CV).")
    if len(rafales["val"]) < 6:
        alertes.append(f"val ne contient que {len(rafales['val'])} rafales : le seuil est fragile. "
                       "Comparer avec les seuils choisis dans les 5 plis de la validation croisée.")
    if hist and len(hist) >= hp["epochs"]:
        alertes.append("toutes les époques ont été faites : le modèle progressait peut-être encore.")
    L = [f"# Rapport d'entraînement : qualité 702, version {args.version}", "",
         f"Date : {config['date']}  ", f"Durée : {duree:.0f} s  ",
         f"Versions : Ultralytics {ultralytics.__version__}, PyTorch {torch.__version__}, "
         f"Python {platform.python_version()}, {platform.system()}  ",
         f"GPU : {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'aucun (CPU)'}", "",
         "## 1. Données", "",
         f"Dossier source : `{dataset}`  ",
         f"Test ajouté à l'entraînement : {'oui' if args.fusionner_test else 'non'}", "",
         "| Bloc | Classe | Images |", "|---|---|---|"]
    L += [f"| {b} | {c} | {n} |" for (b, c), n in sorted(compte.items())]
    L += ["", f"Rafales (pièces) en entraînement : {', '.join(rafales['train'])}  ",
          f"Rafales (pièces) en val : {', '.join(rafales['val'])}", "",
          "Pourquoi val reste à part : il sert à choisir la meilleure époque et le seuil. "
          "Les vraies performances du modèle sont celles de la validation croisée, pas celles de val.", "",
          "## 2. Hyperparamètres", "", "| Paramètre | Valeur |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in hp.items()]
    L += ["", "## 3. Déroulé de l'entraînement", ""]
    if hist:
        k = int(np.nanargmax([h["acc"] for h in hist]))
        L += [f"{len(hist)} époques faites sur {hp['epochs']} ; meilleure précision val {hist[k]['acc']:.3f} "
              f"à l'époque {hist[k]['epoch']} (poids gardés = ceux de cette époque).", "",
              "| Époque | Perte train | Perte val | Précision val |", "|---|---|---|---|"]
        L += [f"| {h['epoch']} | {h['train_loss']:.3f} | {h['val_loss']:.3f} | {h['acc']:.3f} |" for h in hist]
    else:
        L.append("results.csv introuvable.")
    L += ["", "## 4. Seuil de décision", "",
          f"Seuil NOK : **{seuil:.4f}** ({origine}).  ",
          f"Sur val avec ce seuil : {int(pred[y == 1].sum())}/{int((y == 1).sum())} photos NOK arrêtées "
          f"({pct(rappel_val)}), {int(pred[y == 0].sum())}/{int((y == 0).sum())} photos OK rejetées ({pct(fr_val)}).", "",
          "Ces chiffres sont optimistes (val a servi à choisir l'époque et le seuil). "
          "Chiffres à annoncer : ceux de la validation croisée (synthese_c3f.md).", "",
          "## 5. Fichiers produits", "",
          "- `modele.pt` : poids", "- `config_qualite702.yaml` : configuration d'inférence (à livrer avec les poids)",
          "- `entrainement/` : sorties brutes d'Ultralytics (courbes, results.csv)", "",
          "## 6. Alertes", ""]
    L += [f"- {a}" for a in alertes] or ["- aucune"]
    (sortie / "rapport_entrainement.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    shutil.rmtree(donnees, ignore_errors=True)        # dossier temporaire de liens

    print(f"\nVersion {args.version} prête dans {sortie}")
    print(f"Seuil NOK {seuil:.4f} ; val : rappel {pct(rappel_val)}, faux rejets {pct(fr_val)}")
    for a in alertes:
        print("ALERTE :", a)
    print(f"Rapport détaillé : {sortie / 'rapport_entrainement.md'}")


if __name__ == "__main__":
    main()
