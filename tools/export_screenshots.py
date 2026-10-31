"""Copies the screenshots a UI test kept in an .xcresult bundle into a folder, named after their
attachments (`make screenshots`)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile


def main(result_bundle: str, out_dir: str) -> int:
    if not os.path.isdir(result_bundle):
        print(f"no result bundle at {result_bundle}", file=sys.stderr)
        return 1
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["xcrun", "xcresulttool", "export", "attachments",
                        "--path", result_bundle, "--output-path", tmp], check=True)
        manifest_path = os.path.join(tmp, "manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        count = 0
        for test in manifest:
            for attachment in test.get("attachments", []):
                exported = attachment.get("exportedFileName")
                if not exported:
                    continue
                # suggestedHumanReadableName is "<name>_<n>_<UUID>.png"; keep the name.
                name = attachment.get("suggestedHumanReadableName") or exported
                stem, ext = os.path.splitext(name)
                parts = stem.rsplit("_", 2)
                stem = parts[0] if len(parts) == 3 else stem
                shutil.copy(os.path.join(tmp, exported), os.path.join(out_dir, stem + (ext or ".png")))
                count += 1
    print(f"{count} screenshots from {os.path.basename(result_bundle)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
