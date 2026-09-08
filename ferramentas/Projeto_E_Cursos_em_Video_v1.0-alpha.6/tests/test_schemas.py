from __future__ import annotations

import importlib.util
import json
import unittest
import tempfile
import io
from contextlib import redirect_stdout
from pathlib import Path

from projeto_e_video.cli import main


PACKAGE = Path(__file__).resolve().parents[1]


class SchemaTests(unittest.TestCase):
    def test_all_json_files_are_valid_json(self) -> None:
        files = sorted(PACKAGE.rglob("*.json"))
        self.assertGreaterEqual(len(files), 10)
        for path in files:
            with self.subTest(path=path.relative_to(PACKAGE)):
                json.loads(path.read_text(encoding="utf-8"))

    def test_schemas_declare_draft_and_local_id(self) -> None:
        for path in sorted((PACKAGE / "schemas").glob("*.schema.json")):
            with self.subTest(path=path.name):
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertIn("projeto-e.local", value["$id"])

    def test_examples_match_schemas_when_jsonschema_is_available(self) -> None:
        if importlib.util.find_spec("jsonschema") is None:
            self.skipTest("jsonschema não instalado")
        import jsonschema  # type: ignore[import-untyped]

        pairs = (
            ("candidates.example.json", "candidates.schema.json"),
            ("audio_inventory.example.json", "audio_inventory.schema.json"),
            ("evidence_input.example.json", "evidence_input.schema.json"),
        )
        for example_name, schema_name in pairs:
            with self.subTest(example=example_name):
                example = json.loads(
                    (PACKAGE / "examples" / example_name).read_text(encoding="utf-8")
                )
                schema = json.loads(
                    (PACKAGE / "schemas" / schema_name).read_text(encoding="utf-8")
                )
                jsonschema.Draft202012Validator.check_schema(schema)
                jsonschema.validate(example, schema)

    def test_generated_demo_documents_match_every_public_schema(self) -> None:
        if importlib.util.find_spec("jsonschema") is None:
            self.skipTest("jsonschema não instalado")
        import jsonschema  # type: ignore[import-untyped]

        with tempfile.TemporaryDirectory() as name:
            workspace = Path(name) / "demo"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["demo", "--workspace", str(workspace)]), 0)
            pairs = (
                ("ingest/source_manifest.json", "source_manifest.schema.json"),
                ("ledgers/unit_ledger.json", "unit_ledger.schema.json"),
                ("ledgers/search_queries.json", "search_queries.schema.json"),
                ("ledgers/candidates.json", "candidates.schema.json"),
                ("ledgers/audio_inventory.json", "audio_inventory.schema.json"),
                ("evidence/evidence_input.json", "evidence_input.schema.json"),
                ("audit/audit.json", "audit.schema.json"),
                ("course/course.json", "course.schema.json"),
            )
            for document_name, schema_name in pairs:
                with self.subTest(document=document_name):
                    document = json.loads(
                        (workspace / document_name).read_text(encoding="utf-8")
                    )
                    schema = json.loads(
                        (PACKAGE / "schemas" / schema_name).read_text(encoding="utf-8")
                    )
                    jsonschema.validate(document, schema)


if __name__ == "__main__":
    unittest.main()
