from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from projeto_e_video.ingest import ingest
from projeto_e_video.planning import create_plan, import_map
from projeto_e_video.prompts import write_all_prompts
from projeto_e_video.util import atomic_write_json, read_json


class PromptTests(unittest.TestCase):
    def test_large_draft_produces_bounded_prompts_and_no_search_queries(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "livro.md"
            source.write_text(
                "\n\n".join(
                    f"# Seção {index}\nDefina o conceito {index}, explique e dê um exemplo completo."
                    for index in range(1, 181)
                ),
                encoding="utf-8",
            )
            workspace = base / "workspace"
            workspace.mkdir()
            ingest(str(source), workspace)
            draft = create_plan(workspace)
            paths = write_all_prompts(workspace)

            queries = read_json(workspace / "ledgers" / "search_queries.json")
            self.assertLessEqual(len(draft["units"]), 32)
            self.assertTrue(
                draft["units"][0]["source_locators"][0].endswith(
                    "#sections:1-6"
                )
            )
            self.assertTrue(
                draft["units"][-1]["source_locators"][0].endswith(
                    "#sections:175-180"
                )
            )
            self.assertEqual(queries["queries"], [])
            self.assertIn(
                "BUSCA BLOQUEADA",
                (workspace / "prompts" / "02_BUSCAR_CANDIDATOS.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertTrue(all(path.stat().st_size < 120_000 for path in paths))

    def test_verified_map_search_prompt_is_an_index_not_a_ledger_copy(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "capitulo.md"
            source.write_text(
                "\n\n".join(
                    f"# Seção {index}\nExplique o conceito {index} e aplique em exemplo."
                    for index in range(1, 46)
                ),
                encoding="utf-8",
            )
            workspace = base / "workspace"
            workspace.mkdir()
            ingest(str(source), workspace)
            draft = create_plan(workspace)
            refined = copy.deepcopy(draft)
            for unit in refined["units"]:
                unit["verification_state"] = "VERIFIED_BY_HUMAN"
            map_path = base / "map.json"
            atomic_write_json(map_path, refined)
            import_map(workspace, map_path)
            write_all_prompts(workspace)

            prompt_path = workspace / "prompts" / "02_BUSCAR_CANDIDATOS.md"
            prompt = prompt_path.read_text(encoding="utf-8")
            query_path = workspace / "ledgers" / "search_queries.json"
            self.assertGreater(query_path.stat().st_size, prompt_path.stat().st_size)
            self.assertLess(prompt_path.stat().st_size, 120_000)
            self.assertIn('"truncated": true', prompt)
            self.assertIn("EXACT_OBJECT", prompt)


if __name__ == "__main__":
    unittest.main()
