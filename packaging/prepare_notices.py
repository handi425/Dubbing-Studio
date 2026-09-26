"""Preserve installed dependency licenses and media build provenance."""
import importlib.metadata
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
target = root / "build" / "notices"
target.mkdir(parents=True, exist_ok=True)
versions = []
for dist in importlib.metadata.distributions():
    name = dist.metadata["Name"]
    versions.append(f"{name}=={dist.version}")
    for file in dist.files or []:
        if any(part.lower().startswith(("license", "copying", "notice")) for part in file.parts):
            source = Path(dist.locate_file(file))
            if source.is_file():
                dest = target / name / str(file).replace("..", "_")
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
(target / "DEPENDENCIES.txt").write_text("\n".join(sorted(versions)) + "\n", encoding="utf-8")
ffmpeg = Path(shutil.which("ffmpeg")).parent.parent
for name in ("LICENSE", "README.txt"):
    shutil.copy2(ffmpeg / name, target / f"FFmpeg-{name}")
shutil.copy2(root / "data/models/translate-en_id-1_9/README.md", target / "Argos-OPUS-model.md")
shutil.copy2(root / "data/models/supertonic-3/LICENSE", target / "Supertonic-MODEL-LICENSE.txt")
shutil.copy2(root / "data/models/supertonic-3/README.md", target / "Supertonic-model-card.md")
shutil.copy2(root / "third_party/supertonic/LICENSE", target / "Supertonic-code-LICENSE.txt")
shutil.copy2(root / "third_party/supertonic/UPSTREAM.md", target / "Supertonic-code-source.md")
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.is_file():
    shutil.copy2(python_license, target / "Python-LICENSE.txt")
print(target)
