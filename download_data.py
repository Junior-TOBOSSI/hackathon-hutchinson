import os
from roboflow import Roboflow
import config

def download_dataset():
    print("Connexion à Roboflow...")
    rf = Roboflow(api_key=config.ROBOFLOW_API_KEY)
    project = rf.workspace(config.ROBOFLOW_WORKSPACE).project(config.ROBOFLOW_PROJECT)
    version = project.version(config.ROBOFLOW_VERSION)
    
    print(f"Téléchargement du dataset dans {config.DATASET_DIR}...")
    dataset = version.download("yolov8", location=config.DATASET_DIR)
    print(f"Téléchargement terminé ! Fichier yaml : {os.path.join(dataset.location, 'data.yaml')}")

if __name__ == "__main__":
    download_dataset()