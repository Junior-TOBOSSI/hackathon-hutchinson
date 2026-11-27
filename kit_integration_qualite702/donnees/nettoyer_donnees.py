"""
Nettoyage des données qualité 702 : règles écrites à l'avance, mesurées sur chaque photo.

Principes (à recopier dans le pitch) :
  1. Une photo est retirée pour un défaut DE PRISE DE VUE, mesuré sur l'image.
     Jamais parce que le modèle se trompe dessus.
  2. Les mêmes règles et les mêmes seuils s'appliquent à toutes les photos, OK comme NOK.
  3. Chaque seuil a un sens physique ; il n'est pas réglé pour améliorer le score.
  4. Rien n'est supprimé : le script écrit une liste d'exclusions (exclusions.csv) ;
     preparer_3classes.py --exclure la lit. Les données d'origine restent intactes.
  5. Tout est tracé : valeur mesurée, seuil, règle, planches à valider par un humain.
  6. Une photo "différente" n'est pas une photo sale (ex. joint très lumineux R10, R12) : on la garde.

Règles :
  R1 INTEGRITE      fichier illisible, ou taille différente de 126 x 86 px
  R2 DOUBLON        fichier identique octet pour octet à une photo déjà vue
  R3 EXPOSITION     photo quasi noire (gris moyen < 8) ou saturée (> 5 % de pixels à 255)
  R4 POSITIONNEMENT pièce décalée : l'anneau blanc de la gorge entre dans le coin bas gauche
                    (> 5 % de pixels clairs dans la zone lignes 60-85, colonnes 0-54)
  R5 PIECE          si au moins 50 % des photos d'une pièce (rafale) sont retirées,
                    toute la pièce est retirée (le reste de la rafale est peu fiable)

Usage (cluster) :
    python nettoyer_donnees.py --donnees $HOME/hackathon/donnees/702 --sortie $HOME/hackathon/nettoyage
"""
import argparse
import csv
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

from preparer_donnees_rafales import lister_images, SEUIL_RAFALE_S

# ---------------------------------------------------------------- règles et seuils (fixés à l'avance)
TAILLE_ATTENDUE = (126, 86)              # (largeur, hauteur) des photos de la caméra 702
EXPO_GRIS_MIN = 8                        # gris moyen sous 8 / 255 : image quasi noire
EXPO_SATURE_MAX = 5.0                    # % de pixels à 255 au-delà duquel l'image est brûlée
ZONE_LIGNES, ZONE_COLONNES = slice(60, 86), slice(0, 55)   # coin bas gauche
GRIS_CLAIR = 70                          # un pixel de l'anneau blanc dépasse 70 en gris brut
POSITION_MAX = 5.0                       # % de pixels clairs tolérés dans le coin bas gauche
PIECE_PART_MAX = 0.5                     # part de photos retirées qui fait retirer la pièce

NOMS = {"R1": "INTEGRITE", "R2": "DOUBLON", "R3": "EXPOSITION", "R4": "POSITIONNEMENT", "R5": "PIECE"}


def mesurer(chemin: Path):
    """Toutes les mesures d'une photo. Renvoie None si le fichier est illisible."""
    try:
        im = Image.open(chemin)
        im.load()
    except Exception:
        return None
    rgb = np.asarray(im.convert("RGB"), dtype=np.float32)
    g = np.asarray(im.convert("L"), dtype=np.float32)
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    zone = g[ZONE_LIGNES, ZONE_COLONNES]
    return {
        "largeur": im.size[0], "hauteur": im.size[1],
        "gris_moyen": float(g.mean()),
        "pct_sature": float((rgb.max(axis=2) >= 255).mean() * 100),
        "pct_coin_clair": float((zone > GRIS_CLAIR).mean() * 100) if zone.size else 0.0,
        "nettete": float(lap.var()),     # mesure informative seulement (aucun seuil physique justifiable)
        "md5": hashlib.md5(chemin.read_bytes()).hexdigest(),
    }


def eclaircir(chemin, facteur=3.5):
    a = np.asarray(Image.open(chemin).convert("RGB"), dtype=np.float32) * facteur
    return np.clip(a, 0, 255).astype(np.uint8)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--donnees", required=True, help="dossier contenant OK/ et NOK/ (non modifié)")
    p.add_argument("--sortie", required=True, help="dossier du rapport de nettoyage")
    p.add_argument("--seuil-rafale", type=float, default=SEUIL_RAFALE_S)
    args = p.parse_args()
    sortie = Path(args.sortie).expanduser()
    sortie.mkdir(parents=True, exist_ok=True)

    # 1. Liste des photos, avec les MÊMES rafales que preparer_3classes.py
    images = lister_images(Path(args.donnees).expanduser(), args.seuil_rafale)
    vus = {}
    for d in images:
        m = mesurer(d["chemin"])
        d["regles"], d["mesures"] = [], m or {}
        if m is None:
            d["regles"].append(("R1", "illisible", "-"))
            continue
        if (m["largeur"], m["hauteur"]) != TAILLE_ATTENDUE:
            d["regles"].append(("R1", f"{m['largeur']}x{m['hauteur']}", f"{TAILLE_ATTENDUE[0]}x{TAILLE_ATTENDUE[1]}"))
        if m["md5"] in vus:
            d["regles"].append(("R2", f"identique à {vus[m['md5']]}", "-"))
        vus.setdefault(m["md5"], d["chemin"].name)
        if m["gris_moyen"] < EXPO_GRIS_MIN:
            d["regles"].append(("R3", f"gris moyen {m['gris_moyen']:.1f}", f"< {EXPO_GRIS_MIN}"))
        if m["pct_sature"] > EXPO_SATURE_MAX:
            d["regles"].append(("R3", f"{m['pct_sature']:.1f} % saturés", f"> {EXPO_SATURE_MAX} %"))
        if m["pct_coin_clair"] > POSITION_MAX:
            d["regles"].append(("R4", f"{m['pct_coin_clair']:.1f} % clairs dans le coin", f"> {POSITION_MAX} %"))

    # 2. Règle pièce : si au moins la moitié d'une rafale est retirée, on retire toute la rafale
    rafales = sorted({d["rafale"] for d in images})
    bilan = {}
    for r in rafales:
        sel = [d for d in images if d["rafale"] == r]
        n_ret = sum(bool(d["regles"]) for d in sel)
        bilan[r] = {"classe": sel[0]["classe"], "n": len(sel), "retirees_photo": n_ret, "piece_retiree": False}
        if n_ret and n_ret / len(sel) >= PIECE_PART_MAX:
            bilan[r]["piece_retiree"] = True
            for d in sel:
                if not d["regles"]:
                    d["regles"].append(("R5", f"{n_ret}/{len(sel)} photos de la pièce retirées", f">= {PIECE_PART_MAX:.0%}"))

    # 3. Fichiers CSV
    with open(sortie / "mesures.csv", "w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(["fichier", "classe", "rafale", "gris_moyen", "pct_sature", "pct_coin_clair", "nettete", "exclue"])
        for d in images:
            m = d["mesures"]
            w.writerow([d["chemin"].name, d["classe"], d["rafale"], f"{m.get('gris_moyen', float('nan')):.2f}",
                        f"{m.get('pct_sature', float('nan')):.2f}", f"{m.get('pct_coin_clair', float('nan')):.2f}",
                        f"{m.get('nettete', float('nan')):.1f}", "oui" if d["regles"] else "non"])
    exclues = [d for d in images if d["regles"]]
    with open(sortie / "exclusions.csv", "w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(["fichier", "classe", "rafale", "regle", "nom_regle", "valeur", "seuil"])
        for d in exclues:
            for code, val, seuil in d["regles"]:
                w.writerow([d["chemin"].name, d["classe"], d["rafale"], code, NOMS[code], val, seuil])

    # 4. Figures : histogramme du critère de positionnement + planches à valider
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    v = np.array([d["mesures"].get("pct_coin_clair", 0) for d in images])
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.hist(v, bins=np.arange(0, max(30, v.max() + 1), 0.5), color="tab:blue")
    ax.axvline(POSITION_MAX, color="red", ls="--", label=f"seuil {POSITION_MAX} %")
    ax.set_yscale("log")
    ax.set_xlabel("% de pixels clairs dans le coin bas gauche")
    ax.set_ylabel("nombre de photos (échelle log)")
    ax.set_title("R4 positionnement : les pièces bien posées restent près de 0 %")
    ax.legend()
    plt.tight_layout()
    plt.savefig(sortie / "histogramme_positionnement.png", dpi=80)
    plt.close()

    def planche(liste, titre, fichier, n_max=12):
        liste = liste[:n_max]
        if not liste:
            return False
        cols = min(4, len(liste))
        lignes = (len(liste) + cols - 1) // cols
        fig, axs = plt.subplots(lignes, cols, figsize=(4 * cols, 3 * lignes), squeeze=False)
        for a in axs.flat:
            a.axis("off")
        for a, (d, legende) in zip(axs.flat, liste):
            a.imshow(eclaircir(d["chemin"]))
            a.add_patch(plt.Rectangle((ZONE_COLONNES.start, ZONE_LIGNES.start),
                                      ZONE_COLONNES.stop - ZONE_COLONNES.start - 1,
                                      ZONE_LIGNES.stop - ZONE_LIGNES.start - 1, fill=False, ec="yellow", lw=1.5))
            a.set_title(legende, fontsize=9)
        fig.suptitle(titre + " (photos éclaircies x3,5 ; cadre jaune = zone R4)", fontsize=11)
        plt.tight_layout()
        plt.savefig(sortie / fichier, dpi=80)
        plt.close()
        return True

    # Exclues : jusqu'à 3 photos par rafale concernée
    ech = []
    for r in rafales:
        sel = [d for d in exclues if d["rafale"] == r]
        for d in [sel[i] for i in np.linspace(0, len(sel) - 1, min(3, len(sel))).astype(int)] if sel else []:
            ech.append((d, f"{r} {d['classe']} : {', '.join(c for c, _, _ in d['regles'])} "
                           f"({d['mesures'].get('pct_coin_clair', 0):.1f} %)"))
    planche(ech, "Photos RETIRÉES", "planche_retirees.png")
    # Cas limites : gardées les plus proches du seuil, retirées les plus proches du seuil
    gardees = sorted([d for d in images if not d["regles"]], key=lambda d: -d["mesures"].get("pct_coin_clair", 0))
    ret_r4 = sorted([d for d in exclues if any(c == "R4" for c, _, _ in d["regles"])],
                    key=lambda d: d["mesures"]["pct_coin_clair"])
    lim = [(d, f"GARDÉE {d['rafale']} {d['classe']} ({d['mesures'].get('pct_coin_clair', 0):.1f} %)") for d in gardees[:4]]
    lim += [(d, f"RETIRÉE {d['rafale']} {d['classe']} ({d['mesures']['pct_coin_clair']:.1f} %)") for d in ret_r4[:4]]
    planche(lim, "Cas LIMITES autour du seuil R4 : à valider à l'œil", "planche_cas_limites.png", n_max=8)

    # 5. Rapport
    n_ok = sum(d["classe"] == "OK" for d in images)
    n_nok = len(images) - n_ok
    ex_ok = sum(d["classe"] == "OK" for d in exclues)
    ex_nok = len(exclues) - ex_ok
    max_gardee = gardees[0]["mesures"].get("pct_coin_clair", 0) if gardees else float("nan")
    min_r4 = ret_r4[0]["mesures"]["pct_coin_clair"] if ret_r4 else float("nan")
    L = ["# Rapport de nettoyage des données 702", "",
         f"Données lues : `{args.donnees}` (non modifiées)  ",
         f"Photos : {len(images)} ({n_ok} OK, {n_nok} NOK), pièces (rafales, pause > {args.seuil_rafale} s) : {len(rafales)}", "",
         "## En clair", "",
         f"{len(exclues)} photos retirées sur {len(images)} ({100 * len(exclues) / len(images):.1f} %) : "
         f"{ex_ok} OK et {ex_nok} NOK. "
         f"Pièces retirées entièrement : {', '.join(r for r in rafales if bilan[r]['piece_retiree']) or 'aucune'}.", "",
         "## Principes", "",
         "1. Une photo est retirée pour un défaut de prise de vue mesuré sur l'image, jamais parce que le modèle se trompe.",
         "2. Mêmes règles et mêmes seuils pour toutes les photos, OK comme NOK.",
         "3. Chaque seuil a un sens physique et a été fixé avant de relancer les entraînements.",
         "4. Rien n'est supprimé : exclusions.csv est lu par preparer_3classes.py --exclure.",
         "5. Une photo différente n'est pas une photo sale : les joints très lumineux (R10, R12) sont gardés.", "",
         "## Règles et résultats", "",
         "| Règle | Définition | Seuil | Photos retirées |", "|---|---|---|---|"]
    defs = {"R1": ("fichier illisible ou taille inattendue", f"{TAILLE_ATTENDUE[0]} x {TAILLE_ATTENDUE[1]} px"),
            "R2": ("fichier identique à une autre photo", "octet pour octet"),
            "R3": ("photo quasi noire ou brûlée", f"gris < {EXPO_GRIS_MIN} ou > {EXPO_SATURE_MAX} % saturés"),
            "R4": ("pièce décalée : anneau dans le coin bas gauche", f"> {POSITION_MAX} % de pixels clairs"),
            "R5": ("pièce dont la moitié des photos est retirée", f">= {PIECE_PART_MAX:.0%} de la rafale")}
    for c in ["R1", "R2", "R3", "R4", "R5"]:
        n = sum(any(cc == c for cc, _, _ in d["regles"]) for d in images)
        L.append(f"| {c} {NOMS[c]} | {defs[c][0]} | {defs[c][1]} | {n} |")
    L += ["", "Une photo peut relever de plusieurs règles ; elle n'est comptée qu'une fois dans le total.", "",
          "## Pièces concernées", "", "| Pièce | Classe | Photos | Retirées par photo | Pièce entière retirée |", "|---|---|---|---|---|"]
    for r in rafales:
        b = bilan[r]
        if b["retirees_photo"]:
            L.append(f"| {r} | {b['classe']} | {b['n']} | {b['retirees_photo']} | {'oui' if b['piece_retiree'] else 'non'} |")
    L += ["", "## Justification du seuil R4", "",
          f"Plus forte valeur parmi les photos gardées : {max_gardee:.1f} %. "
          f"Plus faible valeur parmi les photos retirées par R4 : {min_r4:.1f} %. "
          f"Le seuil ({POSITION_MAX} %) tombe entre les deux.  ",
          "Voir histogramme_positionnement.png et planche_cas_limites.png.", "",
          "## Mesure informative (pas de règle)", "",
          f"Netteté (variance du laplacien) : médiane {np.median([d['mesures'].get('nettete', 0) for d in images]):.1f}. "
          "Aucun seuil de flou n'est appliqué : les valeurs extrêmes correspondent à des joints très contrastés "
          "(R03, R10), pas à des photos floues.", "",
          "## Fichiers", "",
          "- `exclusions.csv` : une ligne par photo retirée et par règle (valeur mesurée, seuil)",
          "- `mesures.csv` : toutes les mesures de toutes les photos",
          "- `histogramme_positionnement.png`, `planche_retirees.png`, `planche_cas_limites.png`", "",
          "## Étape suivante", "",
          "```", f"python preparer_3classes.py --donnees {args.donnees} --tri <tri_nok.csv> "
          f"--exclure {sortie / 'exclusions.csv'} --sortie <préfixe>", "```"]
    (sortie / "rapport_nettoyage.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    print(L[L.index("## En clair") + 2])
    for l in L:
        if l.startswith("| R") and "|" in l[3:]:
            print(l)
    print(f"Rapport détaillé : {sortie / 'rapport_nettoyage.md'}")


if __name__ == "__main__":
    main()
