"""
Évalue une version du modèle qualité 702 avec LE MÊME CODE que la production (qualite702.Qualite702),
et écrit un rapport détaillé. Sert à vérifier l'intégration et à comparer deux versions.

Dossier d'images attendu : des sous-dossiers par classe (OK, NOK_SANS, NOK_DOUBLE ou NOK).
On peut donner directement un bloc préparé, ex. dataset_702_3c_pli1/val.

Sorties dans --sortie :
    metriques.json        chiffres clés (pour comparer les versions)
    predictions.csv       une ligne par photo
    rapport_evaluation.md rapport détaillé

Usage :
    python evaluer.py --config $HOME/hackathon/modeles/qualite702_v1/config_qualite702.yaml \
        --images $HOME/hackathon/dataset_702_3c_pli1/val --sortie $HOME/hackathon/modeles/qualite702_v1/eval_val
    # Comparer avec une version précédente :
    ... --comparer $HOME/hackathon/modeles/qualite702_v0/eval_val/metriques.json
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

from qualite702 import Qualite702


def pct(x):
    return "n/a" if x is None or x != x else f"{100 * x:.1f} %"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", required=True)
    p.add_argument("--images", required=True, help="dossier avec un sous-dossier par classe")
    p.add_argument("--sortie", required=True)
    p.add_argument("--device", default=None, help="cpu ou 0 (par défaut : celui de la config)")
    p.add_argument("--comparer", default=None, help="metriques.json d'une autre version")
    p.add_argument("--note", default="", help="remarque écrite dans le rapport (ex. 'images vues à l'entraînement')")
    args = p.parse_args()

    q = Qualite702(args.config, device=args.device)
    images = Path(args.images).expanduser()
    sortie = Path(args.sortie).expanduser()
    sortie.mkdir(parents=True, exist_ok=True)
    items = [(f, d.name) for d in sorted(images.iterdir()) if d.is_dir() for f in sorted(d.glob("*.jpg"))]
    if not items:
        raise SystemExit(f"ERREUR : aucune image .jpg dans les sous-dossiers de {images}")

    lignes = []
    for f, vraie in items:
        r = q.predire(str(f))
        lignes.append({"fichier": f.name, "vraie_classe": vraie, "vrai": "OK" if vraie == "OK" else "NOK",
                       "verdict": r["verdict"], "type_defaut": r["type_defaut"] or "",
                       "score_nok": r["score_nok"], "latence_ms": r["latence_ms"]})
    with open(sortie / "predictions.csv", "w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(lignes[0]))
        w.writeheader()
        w.writerows(lignes)

    nok = [l for l in lignes if l["vrai"] == "NOK"]
    ok = [l for l in lignes if l["vrai"] == "OK"]
    arretees = sum(l["verdict"] == "NOK" for l in nok)
    doute_nok = sum(l["verdict"] == "A_VERIFIER" for l in nok)
    rejetees = sum(l["verdict"] == "NOK" for l in ok)
    doute_ok = sum(l["verdict"] == "A_VERIFIER" for l in ok)
    lat = np.array([l["latence_ms"] for l in lignes][1:] or [lignes[0]["latence_ms"]])  # 1re image = chauffe
    m = {
        "version": q.info_modele["version"], "images": str(images), "n_photos": len(lignes),
        "n_nok": len(nok), "n_ok": len(ok),
        "rappel": arretees / len(nok) if nok else None,
        "nok_declarees_ok": (len(nok) - arretees - doute_nok) / len(nok) if nok else None,
        "faux_rejets": rejetees / len(ok) if ok else None,
        "a_verifier_ok": doute_ok / len(ok) if ok else None,
        "latence_ms_moyenne": round(float(lat.mean()), 1), "latence_ms_p95": round(float(np.percentile(lat, 95)), 1),
        "seuil_nok": q.seuil, "par_type": {},
    }
    for t in sorted({l["vraie_classe"] for l in nok}):
        sel = [l for l in nok if l["vraie_classe"] == t]
        m["par_type"][t] = {"n": len(sel), "arretees": sum(l["verdict"] == "NOK" for l in sel)}
    (sortie / "metriques.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

    # Matrice de confusion : vraie classe x (verdict OK / A_VERIFIER / type NOK prédit)
    colonnes = ["OK", "A_VERIFIER"] + [c for c in q.classes if c.startswith("NOK")]
    def case(l):
        return l["verdict"] if l["verdict"] in ("OK", "A_VERIFIER") else l["type_defaut"]
    vraies = sorted({l["vraie_classe"] for l in lignes})

    L = [f"# Évaluation qualité 702, version {m['version']}", "",
         f"Images : `{images}` ({len(lignes)} photos : {len(nok)} NOK, {len(ok)} OK)  ",
         f"Seuil NOK : {q.seuil}  ", f"Code utilisé : qualite702.Qualite702 (le même qu'en production)"]
    if args.note:
        L += ["", f"> Remarque : {args.note}"]
    L += ["", "## En clair", "",
          f"Sur 100 photos de pièces mauvaises, le modèle en arrête {100 * (m['rappel'] or 0):.0f}"
          + (f" et en met {100 * doute_nok / len(nok):.0f} en doute" if doute_nok else "") + ".  ",
          f"Sur 100 photos de pièces bonnes, il en rejette {100 * (m['faux_rejets'] or 0):.0f} à tort.  ",
          f"Temps de réponse : {m['latence_ms_moyenne']} ms en moyenne, {m['latence_ms_p95']} ms pour 95 % des photos.", "",
          "## Chiffres", "", "| Mesure | Valeur |", "|---|---|",
          f"| Rappel (photos NOK arrêtées) | {pct(m['rappel'])} ({arretees}/{len(nok)}) |",
          f"| Photos NOK déclarées OK (pire erreur) | {pct(m['nok_declarees_ok'])} |",
          f"| Faux rejets (photos OK rejetées) | {pct(m['faux_rejets'])} ({rejetees}/{len(ok)}) |",
          f"| Photos OK mises en doute | {pct(m['a_verifier_ok'])} |",
          "", "## Par type de défaut", "", "| Type | Photos | Arrêtées | Rappel |", "|---|---|---|---|"]
    L += [f"| {t} | {v['n']} | {v['arretees']} | {pct(v['arretees'] / v['n'])} |" for t, v in m["par_type"].items()]
    L += ["", "## Matrice de confusion", "", "Lignes = vraie classe ; colonnes = décision du modèle.", "",
          "| Vraie \\ décision | " + " | ".join(colonnes) + " |", "|---|" + "---|" * len(colonnes)]
    for v in vraies:
        L.append(f"| {v} | " + " | ".join(str(sum(l["vraie_classe"] == v and case(l) == c for l in lignes))
                                          for c in colonnes) + " |")
    erreurs = [l for l in lignes if (l["vrai"] == "NOK") != (l["verdict"] == "NOK")]
    L += ["", f"## Photos mal classées ({len(erreurs)})", ""]
    if erreurs:
        L += ["| Fichier | Vraie classe | Verdict | Score NOK |", "|---|---|---|---|"]
        L += [f"| {l['fichier']} | {l['vraie_classe']} | {l['verdict']} | {l['score_nok']:.3f} |" for l in erreurs[:60]]
        if len(erreurs) > 60:
            L.append(f"\n(+ {len(erreurs) - 60} autres dans predictions.csv)")
    else:
        L.append("Aucune.")
    if args.comparer:
        a = json.loads(Path(args.comparer).expanduser().read_text(encoding="utf-8"))
        L += ["", f"## Comparaison avec la version {a.get('version')}", "",
              f"Images de l'autre évaluation : `{a.get('images')}`"
              + ("" if a.get("images") == m["images"] else " (ATTENTION : pas les mêmes images, comparaison faussée)"), "",
              f"| Mesure | {a.get('version')} | {m['version']} |", "|---|---|---|"]
        for k, nom in [("rappel", "Rappel"), ("faux_rejets", "Faux rejets"), ("nok_declarees_ok", "NOK déclarées OK")]:
            L.append(f"| {nom} | {pct(a.get(k))} | {pct(m[k])} |")
        L.append(f"| Latence moyenne | {a.get('latence_ms_moyenne')} ms | {m['latence_ms_moyenne']} ms |")
    (sortie / "rapport_evaluation.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    print(L[L.index("## En clair") + 2])
    print(L[L.index("## En clair") + 3])
    print(L[L.index("## En clair") + 4])
    print(f"Rapport détaillé : {sortie / 'rapport_evaluation.md'}")


if __name__ == "__main__":
    main()
