import sys
import os
import cv2
from pathlib import Path

# Add current directory to path
sys.path.append(os.getcwd())

import app

def test_prediction():
    print("Testing Freshness Detection...")
    
    # Path to a test image
    # Using one of the icon assets as a proxy for an image
    test_image_path = r"E:\nutrifresh\nutrifresh_app\assets\icons\fruits\apple.png"
    
    if not os.path.exists(test_image_path):
        print(f"Test image not found at {test_image_path}")
        return

    print(f"Reading image from: {test_image_path}")
    img = cv2.imread(test_image_path)
    
    if img is None:
        print("Failed to read image")
        return

    print("Running analysis...")
    result, error = app.analyze_image(img)
    
    if error:
        print(f"Error: {error}")
    else:
        print("Success! Result:")
        import json
        print(json.dumps(result, indent=2))

if __name__ == "__main__":
    test_prediction()
