"""
Exporte une version du modèle qualité 702 au format ONNX, puis VÉRIFIE que l'ONNX donne les mêmes
réponses que le .pt et mesure les temps de réponse sur le processeur (CPU).

ONNX = format standard de modèle, lisible sans PyTorch (onnxruntime), plus léger à déployer.

Sorties dans le dossier de la version :
    modele.onnx                      modèle exporté
    config_qualite702_onnx.yaml      même config, mais pointant vers modele.onnx
    rapport_export.md                écarts .pt / .onnx et latences

Usage :
    python export_onnx.py --config $HOME/hackathon/modeles/qualite702_v1/config_qualite702.yaml \
        --images $HOME/hackathon/dataset_702_3c_pli1/val
"""
import argparse
import shutil
import time
from pathlib import Path

import numpy as np
import yaml

from qualite702 import Qualite702


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", required=True)
    p.add_argument("--images", required=True, help="dossier d'images (sous-dossiers acceptés) pour la vérification")
    p.add_argument("--n", type=int, default=100, help="nombre d'images comparées")
    args = p.parse_args()

    chemin_cfg = Path(args.config).expanduser().resolve()
    dossier = chemin_cfg.parent
    cfg = yaml.safe_load(chemin_cfg.read_text(encoding="utf-8"))
    from ultralytics import YOLO
    exporte = YOLO(str(dossier / cfg["modele"])).export(format="onnx", imgsz=cfg["imgsz"], dynamic=False)
    onnx = dossier / "modele.onnx"
    if Path(exporte).resolve() != onnx.resolve():
        shutil.copy2(exporte, onnx)

    cfg_onnx = dict(cfg, modele="modele.onnx")
    chemin_onnx = dossier / "config_qualite702_onnx.yaml"
    with open(chemin_onnx, "w", encoding="utf-8") as h:
        yaml.safe_dump(cfg_onnx, h, allow_unicode=True, sort_keys=False)

    images = sorted(Path(args.images).expanduser().rglob("*.jpg"))
    if not images:
        raise SystemExit("ERREUR : aucune image .jpg trouvée")
    images = [images[i] for i in np.linspace(0, len(images) - 1, min(args.n, len(images))).astype(int)]

    q_pt, q_onnx = Qualite702(chemin_cfg, device="cpu"), Qualite702(chemin_onnx, device="cpu")
    ecarts, desaccords, t_pt, t_onnx = [], 0, [], []
    for f in images:
        t0 = time.perf_counter(); a = q_pt.probabilites(str(f)); t_pt.append(time.perf_counter() - t0)
        t0 = time.perf_counter(); b = q_onnx.probabilites(str(f)); t_onnx.append(time.perf_counter() - t0)
        ecarts.append(float(np.abs(a - b).max()))
        desaccords += q_pt.interpreter(a)["verdict"] != q_onnx.interpreter(b)["verdict"]
    ms = lambda t: 1000 * float(np.mean(t[1:] or t))      # on ignore la 1re image (chauffe)
    ok = max(ecarts) < 1e-3 and desaccords == 0
    L = ["# Export ONNX : qualité 702, version " + str(cfg.get("version")), "",
         f"Fichier : `{onnx}` ({onnx.stat().st_size / 1e6:.1f} Mo)  ",
         f"Images comparées : {len(images)}", "",
         "| Mesure | Valeur |", "|---|---|",
         f"| Écart max de probabilité .pt / .onnx | {max(ecarts):.2e} |",
         f"| Verdicts différents | {desaccords} |",
         f"| Latence CPU .pt (moyenne) | {ms(t_pt):.1f} ms |",
         f"| Latence CPU .onnx (moyenne) | {ms(t_onnx):.1f} ms |", "",
         ("Verdict : ONNX conforme, utilisable à la place du .pt (config_qualite702_onnx.yaml)." if ok else
          "ATTENTION : l'ONNX ne donne pas exactement les mêmes réponses. Livrer le .pt tant que ce n'est pas compris."),
         "", "Latences mesurées sur le processeur de la machine qui a lancé ce script : "
         "à remesurer sur le PC de démo."]
    (dossier / "rapport_export.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[6:12]))
    print(f"Rapport détaillé : {dossier / 'rapport_export.md'}")


if __name__ == "__main__":
    main()
