#!/usr/bin/env python3
import argparse

import torch

from vcd.runtime import detect_device, device_info, synchronize


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    device = detect_device(args.device)
    output = torch.ones(4).to(device) + 1
    synchronize(device)
    print({"device": device, "values": output.cpu().tolist(), "info": device_info(args.backend, device)})


if __name__ == "__main__":
    main()
