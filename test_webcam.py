import cv2
import time
from ultralytics import YOLO
import config

def test_local_webcam():
    model_path = config.FINAL_MODEL_PATH
    print(f"Chargement du modèle : {model_path}")
    model = YOLO(model_path)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Erreur : Impossible d'ouvrir la webcam.")
        return

    detection_start_time = None
    ALERT_DURATION = 2.0  # Secondes continues avant de déclencher l'alerte

    print("Appuyez sur 'q' pour quitter.")
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        results = model(frame, conf=0.6, verbose=False)
        annotated_frame = results[0].plot()

        # Vérifie si au moins un objet (téléphone) est détecté
        phone_detected = len(results[0].boxes) > 0

        if phone_detected:
            if detection_start_time is None:
                detection_start_time = time.time()
            elif time.time() - detection_start_time >= ALERT_DURATION:
                cv2.putText(
                    annotated_frame,
                    "ALERTE : USAGE DE TELEPHONE !",
                    (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0, 0, 255),
                    3
                )
        else:
            detection_start_time = None

        cv2.imshow("Test Detection Telephone", annotated_frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    test_local_webcam()