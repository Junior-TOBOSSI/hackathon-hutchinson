import os

# --- PARAMÈTRES ROBOFLOW ---
# Remplacez ces valeurs par celles de votre dataset sur Roboflow Universe
ROBOFLOW_API_KEY = "VOTRE_CLE_API_ICI"
ROBOFLOW_WORKSPACE = "nom-du-workspace"
ROBOFLOW_PROJECT = "nom-du-projet"
ROBOFLOW_VERSION = 1

# --- CHEMINS ---
DATASET_DIR = os.path.abspath("dataset")
OUTPUT_DIR = os.path.abspath("output")
FINAL_MODEL_PATH = os.path.join(OUTPUT_DIR, "phone_objects.pt")

# --- PARAMÈTRES D'ENTRAÎNEMENT ---
BASE_MODEL = "yolov8s.pt"  # yolov8n.pt (plus rapide) ou yolov8s.pt (plus précis)
EPOCHS = 40
IMG_SIZE = 640
BATCH_SIZE = 16            # Montez à 32 si le GPU de JupyterHub a beaucoup de VRAM
PATIENCE = 10              # Arrêt anticipé si le modèle stagne