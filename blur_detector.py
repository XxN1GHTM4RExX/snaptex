import cv2
import numpy as np


def calculate_blur_score(image_bytes: bytes) -> float:
    """
    Convertit les octets de l'image en niveaux de gris, redimensionne l'image
    pour normaliser la résolution, puis calcule la variance du Laplacien.
    """
    # Conversion des octets en tableau NumPy
    np_array = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(np_array, cv2.IMREAD_GRAYSCALE)

    if image is None:
        raise ValueError("Impossible de décoder les octets en image valide.")

    # Normalisation de la largeur à 800px pour éviter la distorsion due à la résolution
    height, width = image.shape
    target_width = 800
    if width > target_width:
        ratio = target_width / float(width)
        target_height = int(height * ratio)
        image = cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_AREA)

    # Calcul de la variance de l'opérateur Laplacien
    laplacian_variance = cv2.Laplacian(image, cv2.CV_64F).var()
    return float(laplacian_variance)


def is_image_blurry(image_bytes: bytes, threshold: float = 100.0) -> tuple[bool, float]:
    """
    Retourne un tuple : (is_blurry: bool, score: float).
    Le seuil est augmenté à 300.0 pour une vérification plus stricte des documents.
    """
    score = calculate_blur_score(image_bytes)
    return score < threshold, score