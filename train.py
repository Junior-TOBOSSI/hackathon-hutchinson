import os
import shutil
import torch
from ultralytics import YOLO
import config

def train():
    # 1. Vérification du GPU
    if torch.cuda.is_available():
        device = 0
        print(f"GPU détecté : {torch.cuda.get_device_name(0)}")
    else:
        device = "cpu"
        print("ATTENTION : Aucun GPU détecté, l'entraînement se fera sur CPU (très lent).")

    # 2. Vérification du dataset
    yaml_path = os.path.join(config.DATASET_DIR, "data.yaml")
    if not os.path.exists(yaml_path):
        raise FileNotFoundError(
            f"Fichier {yaml_path} introuvable. Lancez d'abord 'python download_data.py'."
        )

    # 3. Lancement de l'entraînement
    print(f"Chargement du modèle de base : {config.BASE_MODEL}")
    model = YOLO(config.BASE_MODEL)

    model.train(
        data=yaml_path,
        epochs=config.EPOCHS,
        imgsz=config.IMG_SIZE,
        batch=config.BATCH_SIZE,
        device=device,
        patience=config.PATIENCE,
        project="runs_phone",
        name="train_v1",
        exist_ok=True
    )

    # 4. Export du meilleur modèle dans le dossier output/
    best_weights = os.path.join("runs_phone", "train_v1", "weights", "best.pt")
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    
    if os.path.exists(best_weights):
        shutil.copy(best_weights, config.FINAL_MODEL_PATH)
        print(f"\nSuccès ! Modèle prêt à être téléchargé ici : {config.FINAL_MODEL_PATH}")
    else:
        print("\nErreur : le fichier best.pt n'a pas été trouvé.")

if __name__ == "__main__":
    train()