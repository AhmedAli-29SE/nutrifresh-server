"""
Model loading and inference utilities for NutriFresh FastAPI server.
Optimized for custom MobileNetV2 Freshness Detection Model (18 classes).
"""

import os
import json
import warnings
import numpy as np
import tensorflow as tf
from pathlib import Path
import cv2

# Suppress warnings
warnings.filterwarnings('ignore')
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['CUDA_VISIBLE_DEVICES'] = ''  # CPU only

# Global variables
freshness_model = None
idx_to_class = {}

# Paths
BASE_DIR = Path(__file__).parent.parent.resolve()  # server/
MODELS_DIR = BASE_DIR / "models/models/freshness_detection"
FRESHNESS_MODEL_PATH = MODELS_DIR / 'freshness_detector_mobilenetv2.h5'
CLASS_MAPPING_PATH = MODELS_DIR / 'class_mapping.json'

def load_fruit_detection_model():
    """
    Legacy function stub. 
    User requested to skip separate food detection and rely only on the freshness model.
    """
    print("[INFO] Fruit detection model skipped (using combined freshness model).")
    return True

def load_freshness_model():
    """Load the custom MobileNetV2 freshness detection model"""
    global freshness_model, idx_to_class
    
    try:
        print(f"Loading freshness model from {FRESHNESS_MODEL_PATH}...")
        
        if not FRESHNESS_MODEL_PATH.exists():
            print(f"[ERROR] Model file not found at {FRESHNESS_MODEL_PATH}")
            # Fallback for relative paths if run directly
            if Path('freshness_detector_mobilenetv2.h5').exists():
                 freshness_model = tf.keras.models.load_model('freshness_detector_mobilenetv2.h5')
            else:
                 return False
        else:
            freshness_model = tf.keras.models.load_model(str(FRESHNESS_MODEL_PATH))
            
        print("✅ Freshness model loaded successfully.")

        # Load class mapping
        if CLASS_MAPPING_PATH.exists():
            with open(CLASS_MAPPING_PATH, 'r') as f:
                data = json.load(f)
                idx_to_class = data.get('idx_to_class', {})
            print(f"✅ Class mapping loaded ({len(idx_to_class)} classes).")
        else:
            print("[WARNING] Class mapping file not found. Predictions will be raw indices.")
            
        return True
    except Exception as e:
        print(f"[ERROR] Error loading freshness model: {str(e)}")
        return False

def analyze_image(image):
    """
    Analyze image using the 18-class Freshness Model.
    Determines both food type and freshness status in one go.
    
    Args:
        image: numpy array (BGR format from OpenCV)
    """
    global freshness_model, idx_to_class
    
    if freshness_model is None:
        # Try loading on demand
        if not load_freshness_model():
             return None, "Freshness model not loaded"
    
    try:
        # --- Preprocessing ---
        # Resize to 224x224 (MobileNetV2 standard)
        img_resized = cv2.resize(image, (224, 224))
        
        # Convert BGR to RGB
        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        
        # Normalize to [0, 1] (Standard for many MobileNet implementations, user's previous code used /255.0)
        img_array = img_rgb.astype(np.float32) / 255.0
        
        # Batch dimension
        img_array = np.expand_dims(img_array, axis=0)
        
        # --- Inference ---
        predictions = freshness_model.predict(img_array, verbose=0)
        predictions = predictions[0] # Unwrap batch
        
        # Get Top Prediction
        predicted_idx = np.argmax(predictions)
        confidence = float(predictions[predicted_idx])
        
        # Get Label
        class_label = idx_to_class.get(str(predicted_idx), str(predicted_idx))
        
        # --- Post-processing (Parse "freshapples", "rottenbanana", etc.) ---
        food_name = "Unknown"
        freshness_status = "UNKNOWN"
        freshness_score = 0.0
        
        lower_label = class_label.lower().strip()
        
        # Calculate Freshness Score based on Confidence & Label
        # Logic: 
        # - Fresh: High confidence = High Freshness (66-100)
        # - Mid-Fresh: High confidence = Mid Range (33-66)
        # - Rotten: High confidence = LOW Freshness (0-33)
        
        if "fresh" in lower_label and "mid" not in lower_label:
            freshness_status = "Fresh"
            food_name = lower_label.replace("fresh", "").capitalize()
            # Map 0.0-1.0 to 66-100
            freshness_score = 66 + (confidence * 34)
            
        elif "rotten" in lower_label or "stale" in lower_label or "spoiled" in lower_label:
            freshness_status = "Spoiled" # User requested "Spoiled"
            food_name = lower_label.replace("rotten", "").replace("stale", "").replace("spoiled", "").capitalize()
            # Map 0.0-1.0 to 33-0 (High confidence rotten = 0 freshness)
            freshness_score = 33 * (1.0 - confidence)
            
        elif "mid" in lower_label:
             freshness_status = "Mid Fresh"
             food_name = lower_label.replace("mid-fresh", "").replace("mid", "").capitalize()
             # Map 0.0-1.0 to 33-66
             freshness_score = 33 + (confidence * 33)
             
        else:
             food_name = class_label
             freshness_status = "Fresh" # Default fallback
             freshness_score = 50.0

        # Clamp score
        freshness_score = max(0.0, min(100.0, freshness_score))

        # --- Construct Response ---
        # Matching the structure expected by the server
        result = {
            'fruit_name': food_name,
            'fruit_confidence': round(confidence * 100, 2),
            'top_5_predictions': [], 
            
            'freshness_status': freshness_status,
            'freshness_level': freshness_status.replace(" ", "_").lower(),
            'freshness_confidence': round(freshness_score, 2), # This is the REAL freshness score now
            
            'prediction_value': confidence,
            'status_type': "success" if freshness_score > 66 else ("warning" if freshness_score > 33 else "danger")
        }
        
        return result, None

    except Exception as e:
        print(f"Inference error: {e}")
        return None, str(e)
