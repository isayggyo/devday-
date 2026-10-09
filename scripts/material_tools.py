"""Verified project-local binary tools for real S3 storage and PPT conversion."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import shutil
import urllib.request
import zipfile

from node_runtime import ROOT

WEED_URL = "https://github.com/seaweedfs/seaweedfs/releases/download/4.48/windows_amd64.zip"
WEED_HASH = "fe90c04c0620ad1a1c756f86cd5e1443773f56a446688077a4bb5ec04c3cc874"
LO_URL = "https://download.documentfoundation.org/libreoffice/stable/26.2.6/win/x86_64/LibreOffice_26.2.6_Win_x86-64.msi"
LO_HASH = "f9877032fd908beb9c0ddf06df4af5c2e85f419c42e14876c4cce5aae5fb2660"


def download(url, target, expected):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        print("Downloading " + target.name, flush=True)
        temporary = target.with_suffix(target.suffix + ".partial")
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        temporary.replace(target)
    with target.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != expected:
        raise RuntimeError("Official distribution checksum mismatch: " + target.name)


def install_weed():
    target = ROOT / ".tools/seaweedfs"
    if (target / "weed.exe").exists():
        return
    archive = target / "windows_amd64.zip"
    download(WEED_URL, archive, WEED_HASH)
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            if not (target / entry.filename).resolve().is_relative_to(target.resolve()):
                raise RuntimeError("Archive path is outside the tool directory")
        bundle.extractall(target)
    print("SeaweedFS ready", flush=True)


def install_lo():
    target = ROOT / ".tools/libreoffice"
    if (target / "program/soffice.com").exists():
        return
    archive = ROOT / ".tools/downloads/LibreOffice_26.2.6_Win_x86-64.msi"
    download(LO_URL, archive, LO_HASH)
    log = ROOT / "artifacts/infra/libreoffice-extract.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    # Extract cabinets directly: Windows Installer's administrative mode can wait for service elevation.
    extractor_dir = ROOT / ".tools/lessmsi"
    extractor_archive = ROOT / ".tools/downloads/lessmsi-v2.12.9.zip"
    download("https://github.com/activescott/lessmsi/releases/download/v2.12.9/lessmsi-v2.12.9.zip", extractor_archive, "5b4e187e74b184ad3a63ccf06c3d17dae2b8c4b6c298a996dbd51a9f6db29d21")
    with zipfile.ZipFile(extractor_archive) as bundle:
        for entry in bundle.infolist():
            if not (extractor_dir / entry.filename).resolve().is_relative_to(extractor_dir.resolve()):
                raise RuntimeError("Extractor archive path is outside its tool directory")
        bundle.extractall(extractor_dir)
    extraction = ROOT / ".tools/libreoffice-extract"
    with log.open("ab") as output:
        subprocess.run([str(extractor_dir / "lessmsi.exe"), "x", str(archive), str(extraction) + "\\"], stdout=output, stderr=output, check=True, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    candidates = list(extraction.rglob("soffice.com"))
    if len(candidates) != 1 or not candidates[0].resolve().is_relative_to(extraction.resolve()):
        raise RuntimeError("Unexpected LibreOffice extraction layout")
    shutil.copytree(candidates[0].parent.parent, target, dirs_exist_ok=True)
    if not (target / "program/soffice.com").exists():
        raise RuntimeError("LibreOffice extraction did not produce soffice.com")
    print("LibreOffice ready", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("tool", choices=["storage", "libreoffice"])
    args = parser.parse_args()
    install_weed() if args.tool == "storage" else install_lo()
