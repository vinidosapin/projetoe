from __future__ import annotations

import tempfile
import unittest
import warnings
import zipfile
import os
import io
import json
from subprocess import CompletedProcess
from pathlib import Path
from typing import Any
from unittest.mock import patch

from projeto_e_video.ingest import (
    IngestLimits,
    _extract_data,
    _extract_image,
    _extract_pdf,
    _ocr_pdf,
    ingest,
    validate_source_manifest,
)
from projeto_e_video.planning import create_plan
from projeto_e_video.util import ensure_external_workspace


class IngestTests(unittest.TestCase):
    @staticmethod
    def _office_container(parts: dict[str, str]) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name, content in parts.items():
                archive.writestr(name, content)
        return output.getvalue()

    def test_all_declared_office_and_epub_containers_extract_text(self) -> None:
        fixtures = {
            ".docx": {
                "word/document.xml": "<document><p><t>teorema no DOCX</t></p></document>"
            },
            ".pptx": {
                "ppt/slides/slide1.xml": "<slide><t>exemplo no PPTX</t></slide>"
            },
            ".xlsx": {
                "xl/sharedStrings.xml": "<sst><si><t>relatório no XLSX</t></si></sst>",
                "xl/worksheets/sheet1.xml": "<worksheet><c><v>42</v></c></worksheet>",
            },
            ".odt": {"content.xml": "<document><p>capítulo no ODT</p></document>"},
            ".ods": {"content.xml": "<document><p>tabela no ODS</p></document>"},
            ".odp": {"content.xml": "<document><p>slide no ODP</p></document>"},
            ".epub": {
                "OEBPS/chapter1.xhtml": "<html><body><h1>capítulo no EPUB</h1></body></html>"
            },
        }
        for suffix, parts in fixtures.items():
            with self.subTest(suffix=suffix):
                text, extractor, warnings = _extract_data(
                    self._office_container(parts), suffix
                )
                self.assertIn(" no ", text)
                self.assertEqual(extractor, "office_zip_xml")
                self.assertEqual(warnings, [])

    def test_declared_structured_text_formats_extract_content(self) -> None:
        cases = {
            ".html": (b"<html><body><h1>Aula HTML</h1></body></html>", "Aula HTML"),
            ".xml": (b"<course><unit>Aula XML</unit></course>", "Aula XML"),
            ".ipynb": (b'{"cells":[{"cell_type":"markdown","source":["Aula notebook"]}]}', "Aula notebook"),
        }
        for suffix, (data, expected) in cases.items():
            with self.subTest(suffix=suffix):
                text, extractor, warnings = _extract_data(data, suffix)
                self.assertIn(expected, text)
                self.assertNotEqual(extractor, "none")
                self.assertEqual(warnings, [])

    def test_image_ocr_uses_an_installed_language_instead_of_requiring_both(self) -> None:
        completed = CompletedProcess(
            args=["tesseract"], returncode=0, stdout=b"recognized text", stderr=b""
        )
        with patch(
            "projeto_e_video.ingest.shutil.which", return_value="/usr/bin/tesseract"
        ), patch(
            "projeto_e_video.ingest._tesseract_language", return_value="eng"
        ), patch(
            "projeto_e_video.ingest.run_command", return_value=completed
        ) as command:
            text, extractor, warnings = _extract_image(Path("exercise.png"))
        self.assertEqual(text, "recognized text")
        self.assertEqual(extractor, "tesseract")
        self.assertEqual(warnings, [])
        self.assertEqual(
            command.call_args.args[0],
            ["/usr/bin/tesseract", "exercise.png", "stdout", "-l", "eng"],
        )

    def test_scanned_pdf_reports_explicit_ocr_option(self) -> None:
        completed = CompletedProcess(
            args=["pdftotext"], returncode=0, stdout=b"", stderr=b""
        )
        with patch(
            "projeto_e_video.ingest.shutil.which", return_value="/usr/bin/pdftotext"
        ), patch("projeto_e_video.ingest.run_command", return_value=completed):
            text, extractor, warnings = _extract_pdf(Path("scan.pdf"))
        self.assertEqual(text, "")
        self.assertEqual(extractor, "pdftotext")
        self.assertTrue(any("camada textual" in row for row in warnings))
        self.assertTrue(any("--ocr-scanned-pdf" in row for row in warnings))

    def test_scanned_pdf_opt_in_uses_ocr_fallback(self) -> None:
        completed = CompletedProcess(
            args=["pdftotext"], returncode=0, stdout=b"", stderr=b""
        )
        with patch(
            "projeto_e_video.ingest.shutil.which", return_value="/usr/bin/pdftotext"
        ), patch("projeto_e_video.ingest.run_command", return_value=completed), patch(
            "projeto_e_video.ingest._ocr_pdf",
            return_value=("página um\fpágina dois", "pdftoppm+tesseract", []),
        ) as ocr:
            text, extractor, warnings = _extract_pdf(
                Path("scan.pdf"), ocr_scanned_pdf=True
            )
        ocr.assert_called_once()
        self.assertIn("página dois", text)
        self.assertEqual(extractor, "pdftoppm+tesseract")
        self.assertTrue(any("camada textual" in row for row in warnings))

    def test_pdf_ocr_page_limit_stops_before_rendering(self) -> None:
        limits = IngestLimits(max_pdf_ocr_pages=2)
        with patch(
            "projeto_e_video.ingest.shutil.which", return_value="/usr/bin/tool"
        ), patch(
            "projeto_e_video.ingest._pdf_page_count", return_value=(3, None)
        ), patch("projeto_e_video.ingest.run_command") as command:
            text, extractor, warnings = _ocr_pdf(Path("scan.pdf"), limits)
        command.assert_not_called()
        self.assertEqual(text, "")
        self.assertEqual(extractor, "pdftoppm+tesseract")
        self.assertTrue(any("limitado a 2" in row for row in warnings))

    def test_manifest_records_pdf_ocr_choice(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            workspace.mkdir()
            manifest = ingest(
                "inferência estatística", workspace, ocr_scanned_pdf=True
            )
            self.assertTrue(manifest["limits"]["ocr_scanned_pdf"])

    def test_empty_input_never_means_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "não podem ser vazias"):
                ingest("", workspace)
            self.assertEqual(list(workspace.iterdir()), [])

    def test_empty_additional_source_rejects_entire_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "source.md"
            source.write_text("conteúdo", encoding="utf-8")
            workspace = base / "workspace"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "não podem ser vazias"):
                ingest(str(source), workspace, extra_inputs=["   "])
            self.assertEqual(list(workspace.iterdir()), [])

    def test_default_limits_cover_large_educational_files(self) -> None:
        limits = IngestLimits()
        self.assertEqual(limits.max_file_bytes, 64 * 1024 * 1024)
        self.assertEqual(limits.max_url_bytes, 64 * 1024 * 1024)
        self.assertEqual(limits.max_extracted_chars, 32_000_000)

    def test_limit_failure_leaves_workspace_empty(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "large.md"
            source.write_text("conteúdo verificável " * 20, encoding="utf-8")
            workspace = base / "workspace"
            workspace.mkdir()
            limits = IngestLimits(max_extracted_chars=20)
            with self.assertRaisesRegex(ValueError, "texto extraído excede"):
                ingest(str(source), workspace, limits=limits)
            self.assertEqual(list(workspace.iterdir()), [])
            self.assertEqual(list(base.glob(".workspace.ingest-*")), [])

    def test_file_limit_failure_leaves_workspace_empty(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "large.md"
            source.write_text("mais de dez bytes", encoding="utf-8")
            workspace = base / "workspace"
            workspace.mkdir()
            limits = IngestLimits(max_file_bytes=10)
            with self.assertRaisesRegex(ValueError, "arquivo excede"):
                ingest(str(source), workspace, limits=limits)
            self.assertEqual(list(workspace.iterdir()), [])

    def test_topic_is_preserved_as_source(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            workspace.mkdir()
            manifest = ingest("aprender transformada de Fourier", workspace)
            self.assertEqual(manifest["input"]["kind"], "TOPIC")
            self.assertEqual(manifest["extracted_source_count"], 1)
            self.assertTrue(manifest["sources"][0]["sha256"])

    def test_long_literal_is_not_misread_as_path(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            workspace.mkdir()
            literal = "Explique probabilidade condicional com exemplos. " * 200
            manifest = ingest(literal, workspace)
            self.assertEqual(manifest["input"]["kind"], "TOPIC")
            self.assertEqual(manifest["source_count"], 1)

    def test_noncontiguous_sources_share_one_hashed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            first = base / "capitulo.md"
            second_dir = base / "outra-pasta"
            second_dir.mkdir()
            second = second_dir / "exercicios.md"
            first.write_text("# Teoria\nDefina esperança.", encoding="utf-8")
            second.write_text("# Exercícios\nResolva E(X).", encoding="utf-8")
            workspace = base / "workspace"
            workspace.mkdir()
            manifest = ingest(
                str(first), workspace, extra_inputs=[str(second)], title="Pacote"
            )
            self.assertEqual(manifest["input"]["kind"], "BUNDLE")
            self.assertEqual(manifest["source_count"], 2)
            self.assertEqual(
                validate_source_manifest(workspace, manifest)[
                    "external_source_verified_count"
                ],
                2,
            )

    def test_explicit_flashlist_folder_expands_to_one_typed_unit_per_item(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            bundle = base / "FlashList_Relatorio_Semanal_20260824_20260830"
            images = bundle / "images"
            images.mkdir(parents=True)
            pdf = bundle / "relatorio_semanal.pdf"
            pdf.write_bytes(b"apresentacao-pdf-nao-autoritativa")
            items = []
            assets = []
            difficulties = ("easy", "hard", "unresolved")
            for index, difficulty in enumerate(difficulties, start=1):
                asset_ref = f"asset-{index:04d}"
                item_ref = f"item-{index:04d}"
                file_name = f"images/{asset_ref}.png"
                (bundle / file_name).write_bytes(f"imagem-{index}".encode())
                assets.append({"asset_ref": asset_ref, "file": file_name})
                items.append(
                    {
                        "item_ref": item_ref,
                        "asset_ref": asset_ref,
                        "difficulty": {"key": difficulty, "label": difficulty},
                        "availability": {"key": "frozen", "label": "Congelada"},
                        "context": {
                            "discipline": "Exercícios de Probabilidades 2",
                            "physical_topic": f"Rolla_Lima_1_{index}",
                        },
                    }
                )
            flashlist: dict[str, Any] = {
                "schema_name": "flashlist.weekly-study",
                "schema_version": 1,
                "scope": {
                    "local_start_date": "2026-08-24",
                    "local_end_date": "2026-08-30",
                },
                "items": items,
                "assets": assets,
            }
            (bundle / "manifest.json").write_text(
                json.dumps(flashlist), encoding="utf-8"
            )
            workspace = base / "workspace"
            workspace.mkdir()
            with patch(
                "projeto_e_video.ingest._extract_image",
                side_effect=lambda path: (
                    f"Exercício reconhecido em {path.stem}",
                    "tesseract",
                    [],
                ),
            ):
                manifest = ingest(str(bundle), workspace)
            self.assertEqual(manifest["source_count"], 3)
            self.assertEqual(
                {row["kind"] for row in manifest["sources"]},
                {"FLASHLIST_ITEM"},
            )
            ledger = create_plan(workspace)
            self.assertEqual(len(ledger["units"]), 3)
            self.assertEqual(
                [row["route_policy"] for row in ledger["units"]],
                ["CONTROL_NO_AUTOMATIC", "OPTIONAL", "REQUIRED"],
            )
            self.assertTrue(
                all(
                    row["product"] == "CURSO_DE_RESOLUCOES_DE_EXERCICIOS"
                    for row in ledger["units"]
                )
            )
            self.assertTrue(all("Rolla_Lima" in row["title"] for row in ledger["units"]))
            validation = validate_source_manifest(workspace, manifest)
            self.assertEqual(validation["external_source_verified_count"], 3)

            flashlist["items"][2]["difficulty"]["key"] = "easy"
            (bundle / "manifest.json").write_text(
                json.dumps(flashlist), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "fonte externa mudou"):
                validate_source_manifest(workspace, manifest)

    def test_report_pdf_does_not_implicitly_ingest_sibling_flashlist_assets(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            bundle = base / "relatorio"
            images = bundle / "images"
            images.mkdir(parents=True)
            pdf = bundle / "relatorio_semanal.pdf"
            pdf.write_bytes(b"pdf-autonomo")
            (images / "asset-0001.png").write_bytes(b"imagem-mutavel")
            flashlist = {
                "schema_name": "flashlist.weekly-study",
                "schema_version": 1,
                "items": [
                    {"item_ref": "item-0001", "asset_ref": "asset-0001"}
                ],
                "assets": [
                    {"asset_ref": "asset-0001", "file": "images/asset-0001.png"}
                ],
            }
            (bundle / "manifest.json").write_text(
                json.dumps(flashlist), encoding="utf-8"
            )
            workspace = base / "workspace"
            workspace.mkdir()
            manifest = ingest(str(pdf), workspace)
            self.assertEqual(manifest["source_count"], 1)
            self.assertEqual(manifest["sources"][0]["kind"], "FILE")
            self.assertEqual(manifest["sources"][0]["exact_locator"], str(pdf))

            (images / "asset-0001.png").unlink()
            validation = validate_source_manifest(workspace, manifest)
            self.assertEqual(validation["external_source_verified_count"], 1)

    def test_flashlist_missing_asset_is_explicit_instead_of_generic_pdf_page(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            bundle = base / "relatorio"
            bundle.mkdir()
            pdf = bundle / "relatorio_semanal.pdf"
            pdf.write_bytes(b"pdf")
            flashlist = {
                "schema_name": "flashlist.weekly-study",
                "schema_version": 1,
                "items": [
                    {
                        "item_ref": "item-0001",
                        "asset_ref": "asset-0001",
                        "difficulty": {"key": "unresolved", "label": "Impossível"},
                        "context": {
                            "discipline": "Inferência Estatística I",
                            "physical_topic": "DeGroot 7.6.5",
                        },
                    }
                ],
                "assets": [
                    {"asset_ref": "asset-0001", "file": "images/asset-0001.png"}
                ],
            }
            (bundle / "manifest.json").write_text(
                json.dumps(flashlist), encoding="utf-8"
            )
            workspace = base / "workspace"
            workspace.mkdir()
            manifest = ingest(str(bundle / "manifest.json"), workspace)
            ledger = create_plan(workspace)
            self.assertEqual(len(ledger["units"]), 1)
            unit = ledger["units"][0]
            self.assertEqual(unit["route_policy"], "REQUIRED")
            self.assertEqual(unit["product"], "CURSO_DE_RESOLUCOES_DE_EXERCICIOS")
            self.assertTrue(unit["extraction_gap"])
            self.assertIn("DeGroot 7.6.5", unit["title"])
            self.assertTrue(
                any("asset declarado" in warning for warning in manifest["sources"][0]["warnings"])
            )

    def test_manifest_detects_external_source_drift(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "fonte.md"
            source.write_text("conteúdo original", encoding="utf-8")
            workspace = base / "workspace"
            workspace.mkdir()
            manifest = ingest(str(source), workspace)
            source.write_text("conteúdo alterado", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fonte externa mudou"):
                validate_source_manifest(workspace, manifest)

    def test_markdown_and_unknown_file_are_inventoried(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "source"
            source.mkdir()
            (source / "a.md").write_text("# Aula\nConteúdo", encoding="utf-8")
            (source / "obj.bin").write_bytes(b"\x00\x01")
            workspace = base / "workspace"
            workspace.mkdir()
            manifest = ingest(str(source), workspace)
            states = {row["extraction_status"] for row in manifest["sources"]}
            self.assertEqual(manifest["source_count"], 2)
            self.assertIn("EXTRAIDA", states)
            self.assertIn("EXTRACAO_NAO_DISPONIVEL", states)

    def test_url_without_permission_is_not_downloaded(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            workspace.mkdir()
            manifest = ingest("https://example.com/livro.pdf", workspace)
            self.assertEqual(manifest["input"]["kind"], "URL")
            self.assertEqual(manifest["sources"][0]["extraction_status"], "URL_NAO_BAIXADA")

    def test_network_download_rejects_private_address(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "privada, local ou reservada"):
                ingest("http://127.0.0.1/private.md", workspace, allow_network=True)

    def test_network_download_rejects_embedded_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "workspace"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "credenciais"):
                ingest(
                    "https://user:password@example.com/aula.md",
                    workspace,
                    allow_network=True,
                )

    def test_invalid_zip_has_operational_error(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            archive = base / "invalid.zip"
            archive.write_bytes(b"not-a-zip")
            workspace = base / "workspace"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "ZIP inválido"):
                ingest(str(archive), workspace)

    def test_zip_member_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            archive = base / "bad.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../escape.md", "não pode")
            workspace = base / "workspace"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "caminho inseguro"):
                ingest(str(archive), workspace)

    def test_safe_zip_preserves_member_locator(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            archive = base / "source.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("capitulo/aula.md", "# Aula\nTexto")
            workspace = base / "workspace"
            workspace.mkdir()
            manifest = ingest(str(archive), workspace)
            self.assertIn("::capitulo/aula.md", manifest["sources"][0]["exact_locator"])

    def test_duplicate_zip_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            archive = base / "duplicate.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(archive, "w") as handle:
                    handle.writestr("a.md", "primeiro")
                    handle.writestr("a.md", "segundo")
            workspace = base / "workspace"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "duplicado"):
                ingest(str(archive), workspace)

    def test_directory_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "source"
            source.mkdir()
            outside = base / "outside.md"
            outside.write_text("segredo externo", encoding="utf-8")
            try:
                os.symlink(outside, source / "link.md")
            except (OSError, NotImplementedError):
                self.skipTest("sistema sem suporte a symlink")
            workspace = base / "workspace"
            workspace.mkdir()
            with self.assertRaisesRegex(ValueError, "link simbólico"):
                ingest(str(source), workspace)

    def test_workspace_inside_package_is_rejected(self) -> None:
        package = Path(__file__).resolve().parents[1]
        with self.assertRaisesRegex(ValueError, "fora da pasta versionada"):
            ensure_external_workspace(package / "workspace-proibido")


if __name__ == "__main__":
    unittest.main()
