import torch
import os

class cv_model:
    model = None

    # Define a startup task
    def __init__(self) -> None:
        print("Loading YOLOV5 Nano model.")
        model_path = os.path.join(os.path.dirname(__file__), 'yolov5n.pt')
        if os.path.exists(model_path):
            self.model = torch.hub.load('ultralytics/yolov5', 'custom', path=model_path)
            print("Model loaded successfully.")
        else:
            print("Model file not found. download it.")
            self.model = torch.hub.load("ultralytics/yolov5", "yolov5n")
            print("Model loaded successfully.")
