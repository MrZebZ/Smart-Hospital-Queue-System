#!/usr/bin/env python3
"""EXPERIMENTAL: count people in a camera/video/image with OpenCV's built-in HOG person detector
and send the count to the server. Frames are processed in memory and never saved (privacy by design).

  pip install -r requirements-camera.txt
  python scripts/people_counter.py --source 0 --hospital 1 --interval 5      # webcam
  python scripts/people_counter.py --source lobby.mp4 --hospital 1 --dry-run # just print counts
HOG is a classic detector: fine for a demo, but use a modern model (e.g. YOLO) for real accuracy.
"""
import argparse
import os
import time

import cv2

from camera_client import send

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp")


def count_people(frame, hog):
    h, w = frame.shape[:2]
    frame = cv2.resize(frame, (640, max(1, int(h * 640 / w))))
    rects, _ = hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.05)
    return len(rects)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default="0", help="camera index, video file or image file")
    p.add_argument("--hospital", type=int, default=1)
    p.add_argument("--url", default="http://127.0.0.1:5000")
    p.add_argument("--key", default=os.environ.get("CAMERA_KEY", "camera-demo-key"))
    p.add_argument("--interval", type=float, default=5)
    p.add_argument("--once", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="print counts, do not contact the server")
    a = p.parse_args()

    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    image = cv2.imread(a.source) if a.source.lower().endswith(IMAGE_EXT) else None
    cap = None if image is not None else cv2.VideoCapture(int(a.source) if a.source.isdigit() else a.source)
    while True:
        frame = image
        if frame is None:
            ok, frame = cap.read()
            if not ok:
                print("No more frames / camera unavailable.")
                break
        n = count_people(frame, hog)
        print(f"people in view: {n}")
        if not a.dry_run:
            print(send(a.url, a.hospital, a.key, n))
        if a.once:
            break
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
