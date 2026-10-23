"""Create once, persist the accepted ID, then run a recoverable native Pipeline."""

import argparse
import hashlib
import json
from pathlib import Path

from haystack import Pipeline

from magic_hour_haystack import (
    MagicHourImageDownloader,
    MagicHourImageGenerator,
    MagicHourImageWaiter,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", default="A tiny orange paper bird on a plain blue background, clean studio photograph")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--submit-only", action="store_true", help="Persist the ID and exit before polling.")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = args.output_dir / "project.json"

    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        print("Resuming image project " + receipt["project_id"])
    else:
        creation = Pipeline()
        creation.add_component("generate", MagicHourImageGenerator())
        receipt = creation.run({"generate": {"prompt": args.prompt}})["generate"]
        # Exclusive write prevents silently replacing an earlier accepted ID.
        with receipt_path.open("x") as output:
            json.dump(receipt, output, indent=2)
        print("Saved image project " + receipt["project_id"])
    if args.submit_only:
        return

    recovery = Pipeline()
    recovery.add_component("wait", MagicHourImageWaiter())
    recovery.add_component("download", MagicHourImageDownloader())
    recovery.connect("wait.project", "download.project")
    result = recovery.run({"wait": {"project_id": receipt["project_id"]}})
    files = []
    for index, image in enumerate(result["download"]["images"]):
        path = args.output_dir / f"image-{index + 1}.bin"
        path.write_bytes(image.data)
        files.append({
            "file": path.name,
            "bytes": len(image.data),
            "sha256": hashlib.sha256(image.data).hexdigest(),
        })
    receipt.update({"status": "complete", "files": files})
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
