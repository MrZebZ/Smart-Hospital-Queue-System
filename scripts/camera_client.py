#!/usr/bin/env python3
"""Pretend to be a CCTV people counter: POST waiting-room counts to the server (standard library only).

Examples:
  python scripts/camera_client.py --hospital 1 --count 14
  python scripts/camera_client.py --hospital 1 --loop 3        # random-walk count every 3 seconds
Run the server with SIMULATE=0 so the built-in simulator does not fight with this script.
"""
import argparse
import json
import os
import random
import time
import urllib.request


def send(url, hospital, key, count):
    req = urllib.request.Request(
        f"{url}/api/dashboard/{hospital}/camera",
        data=json.dumps({"count": count}).encode(),
        headers={"Content-Type": "application/json", "X-Camera-Key": key},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://127.0.0.1:5000")
    p.add_argument("--hospital", type=int, required=True)
    p.add_argument("--key", default=os.environ.get("CAMERA_KEY", "camera-demo-key"))
    p.add_argument("--count", type=int, default=10, help="starting / single count")
    p.add_argument("--loop", type=float, help="repeat every N seconds with a random walk")
    a = p.parse_args()
    n = a.count
    while True:
        print(send(a.url, a.hospital, a.key, n))
        if not a.loop:
            break
        time.sleep(a.loop)
        n = max(0, min(40, n + random.choice([-2, -1, 0, 1, 2])))


if __name__ == "__main__":
    main()
