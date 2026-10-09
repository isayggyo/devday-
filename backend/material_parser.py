import io
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

import olefile
import pymupdf

from .config import get_settings, ROOT


class MaterialError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def validate_material(filename, data):
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix not in {"pdf", "ppt", "pptx"}:
        raise MaterialError("UNSUPPORTED_FILE_TYPE", "PDF, PPT 또는 PPTX 파일을 선택해 주세요.")
    if not data or len(data) > get_settings().material_max_bytes:
        raise MaterialError("INVALID_FILE_SIZE", "자료 파일이 비어 있거나 크기 제한을 초과했습니다.")
    if suffix == "pdf":
        if not data.startswith(b"%PDF-"):
            raise MaterialError("INVALID_PDF", "PDF 형식이 올바르지 않습니다.")
        try:
            with pymupdf.open(stream=data, filetype="pdf") as document:
                if document.is_encrypted:
                    raise MaterialError("ENCRYPTED_PDF", "비밀번호 없는 PDF로 다시 저장해 주세요.")
                if not 1 <= len(document) <= get_settings().material_max_pages:
                    raise MaterialError("PAGE_LIMIT", "자료 페이지 수 제한을 초과했습니다.")
        except MaterialError:
            raise
        except Exception:
            raise MaterialError("INVALID_PDF", "PDF를 읽을 수 없습니다.") from None
    elif suffix == "pptx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as bundle:
                entries = bundle.infolist()
                names = {item.filename for item in entries}
                if "ppt/presentation.xml" not in names or "[Content_Types].xml" not in names:
                    raise ValueError()
                if sum(item.file_size for item in entries) > 150 * 1024 * 1024 or any("vbaProject" in name for name in names):
                    raise MaterialError("UNSUPPORTED_PPTX", "매크로가 없고 압축 해제 크기가 제한 이내인 PPTX를 사용해 주세요.")
        except MaterialError:
            raise
        except Exception:
            raise MaterialError("INVALID_PPTX", "PPTX 형식이 올바르지 않습니다.") from None
    else:
        try:
            with olefile.OleFileIO(io.BytesIO(data)) as document:
                if not document.exists("PowerPoint Document"):
                    raise ValueError()
        except Exception:
            raise MaterialError("INVALID_PPT", "PPT 형식이 올바르지 않습니다.") from None
    return suffix


def convert_presentation(data, suffix):
    executable = Path(get_settings().libreoffice_path)
    if not executable.is_file():
        raise MaterialError("CONVERTER_UNAVAILABLE", "PPT 변환 도구가 준비되지 않았습니다.")
    conversions = ROOT / ".tools/conversions"
    conversions.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=conversions) as name:
        directory = Path(name)
        source = directory / ("lecture." + suffix)
        source.write_bytes(data)
        profile = directory / "profile"
        profile.mkdir()
        (profile / "registrymodifications.xcu").write_text('<oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>', encoding="utf-8")
        command = [str(executable), "-env:UserInstallation=" + profile.as_uri(), "--headless", "--norestore", "--convert-to", "pdf:impress_pdf_Export", "--outdir", str(directory), str(source)]
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
        try:
            process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                process.kill()
            process.communicate()
            raise MaterialError("CONVERSION_TIMEOUT", "PPT 변환 시간이 초과됐습니다.") from None
        output = directory / "lecture.pdf"
        if process.returncode or not output.exists():
            raise MaterialError("CONVERSION_FAILED", "PPT 변환에 실패했습니다. 파일을 확인해 주세요.")
        result = output.read_bytes()
        validate_material("lecture.pdf", result)
        return result


def analyze_pdf(data, store, prefix):
    pages = []
    with pymupdf.open(stream=data, filetype="pdf") as document:
        for number, page in enumerate(document, 1):
            text = page.get_text("text", sort=True).strip()
            key = f"{prefix}/pages/{number}.png"
            scale = min(1.5, 1800 / max(page.rect.width, page.rect.height))
            store.put(key, page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png"), "image/png")
            blocks = [block for block in page.get_text("dict")["blocks"] if block.get("type") == 0]
            images = []
            for index, image in enumerate(page.get_images(full=True)):
                extracted = document.extract_image(image[0])
                ref = f"{prefix}/images/{number}-{index}.{extracted['ext']}"
                store.put(ref, extracted["image"], "application/octet-stream")
                images.append({"ref": ref, "xref": image[0], "width": extracted["width"], "height": extracted["height"]})
            warnings = []
            try:
                tables = [{"bbox": list(table.bbox), "cells": table.extract()} for table in page.find_tables().tables]
            except Exception:
                tables = []
                warnings.append("table_analysis_incomplete")
            vectors = json.loads(json.dumps(page.get_drawings(), default=lambda value: list(value) if hasattr(value, "__iter__") else str(value)))
            pages.append({"page_number": number, "text": text, "description": f"Page {number}: extracted text and original visual preserved" if text else f"Page {number}: requires additional visual analysis",
                "image_ref": key, "metadata_json": {"analysisStatus": "ready" if text and not warnings else "needs_analysis", "width": page.rect.width, "height": page.rect.height, "textBlocks": blocks, "images": images, "tables": tables, "vectorDrawings": vectors, "warnings": warnings,
                    "formulaPolicy": "Original glyphs, text spans and page render preserved; no inferred formula transcription"}})
    return pages
