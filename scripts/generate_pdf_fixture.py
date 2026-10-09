"""Optional fixture regeneration (requires reportlab, not needed to run E2E)."""

import hashlib
import json
from pathlib import Path
import textwrap
import wave

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

DIRECTORY = Path(__file__).resolve().parents[1] / "e2e/fixtures"


def main():
    metadata = json.loads((DIRECTORY / "lecture.json").read_text(encoding="utf-8"))
    document = canvas.Canvas(str(DIRECTORY / metadata["pdf"]), pagesize=letter, invariant=1)
    document.setTitle(metadata["title"])
    document.setAuthor("DevDay E2E fixture")
    for page in metadata["pages"]:
        document.setFont("Helvetica-Bold", 17)
        document.drawString(54, 730, page["title"])
        text = document.beginText(54, 680)
        text.setFont("Helvetica", 11)
        text.setLeading(18)
        for paragraph in page["paragraphs"]:
            for line in textwrap.wrap(paragraph, width=84):
                text.textLine(line)
            text.textLine("")
        document.drawText(text)
        document.setFont("Helvetica", 10)
        document.drawString(54, 40, f"Lecture fixture | source page {page['page']} | CC0-1.0")
        document.showPage()
    document.save()
    for kind in ("pdf", "audio"):
        fixture = DIRECTORY / metadata[kind]
        if fixture.exists():
            metadata[kind + "_sha256"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
    audio = DIRECTORY / metadata["audio"]
    if audio.exists():
        with wave.open(str(audio), "rb") as stream:
            metadata["audio_format"] = {
                "encoding": "PCM",
                "sample_rate": stream.getframerate(),
                "channels": stream.getnchannels(),
                "bits_per_sample": stream.getsampwidth() * 8,
                "duration_seconds": round(stream.getnframes() / stream.getframerate(), 3),
            }
    (DIRECTORY / "lecture.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in metadata.items() if key.endswith("sha256") or key == "audio_format"}, indent=2))


if __name__ == "__main__":
    main()
