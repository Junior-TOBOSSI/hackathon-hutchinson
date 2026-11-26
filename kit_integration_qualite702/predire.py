"""
Test rapide du modèle sur une ou plusieurs photos : affiche le résultat JSON.

Usage :
    python predire.py --config modeles/qualite702_v1/config_qualite702.yaml photo1.jpg photo2.jpg
"""
import argparse
import json

from qualite702 import Qualite702

p = argparse.ArgumentParser()
p.add_argument("--config", required=True)
p.add_argument("--device", default=None)
p.add_argument("photos", nargs="+")
a = p.parse_args()
q = Qualite702(a.config, device=a.device)
for chemin in a.photos:
    print(json.dumps({"photo": chemin, **q.predire(chemin)}, ensure_ascii=False, indent=2))
