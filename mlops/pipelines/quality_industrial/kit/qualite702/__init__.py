"""Modèle qualité référence 702 (Hutchinson) : contrôle du joint dans la gorge.

Usage minimal :
    from qualite702 import Qualite702
    q = Qualite702("config_qualite702.yaml")
    resultat = q.predire("photo.jpg")      # ou image OpenCV (BGR) ou image PIL
"""
from .inference import Qualite702, LIBELLES

__all__ = ["Qualite702", "LIBELLES"]
