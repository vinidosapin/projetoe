from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from projeto_e_video.models import PRODUCT_SOLUTIONS
from projeto_e_video.ingest import ingest
from projeto_e_video.planning import (
    build_queries,
    create_plan,
    import_map,
    validate_refined_map,
)
from projeto_e_video.util import atomic_write_json, read_json


class PlanningTests(unittest.TestCase):
    def test_page_delimited_book_is_bounded_without_losing_page_range(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "book.txt"
            source.write_text(
                "\f".join(
                    f"Página de conteúdo {number}\nDefinição e exemplo substantivo."
                    for number in range(1, 1001)
                ),
                encoding="utf-8",
            )
            workspace = base / "workspace"
            workspace.mkdir()
            ingest(str(source), workspace)
            ledger = create_plan(workspace)
            self.assertEqual(len(ledger["units"]), 32)
            self.assertTrue(
                ledger["units"][0]["source_locators"][0].endswith("#pages:1-32")
            )
            self.assertTrue(
                ledger["units"][-1]["source_locators"][0].endswith(
                    "#pages:993-1000"
                )
            )

    def test_bundle_budget_bounds_v0_across_many_sources(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source_dir = base / "sources"
            source_dir.mkdir()
            pages = "\f".join(
                f"Conteúdo da página {number}." for number in range(1, 81)
            )
            for number in range(64):
                (source_dir / f"source-{number:02d}.txt").write_text(
                    pages, encoding="utf-8"
                )
            workspace = base / "workspace"
            workspace.mkdir()
            ingest(str(source_dir), workspace)
            ledger = create_plan(workspace)
            self.assertEqual(len(ledger["units"]), 128)
            represented = {
                unit["source_ids"][0] for unit in ledger["units"]
            }
            self.assertEqual(len(represented), 64)

    def test_headings_become_units_and_exercise_product_is_separate(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "aula.md"
            source.write_text(
                "# Teoria de grafos\nDefina vértices e arestas.\n\n# Questão prática\nResolva o menor caminho e confira.",
                encoding="utf-8",
            )
            workspace = base / "workspace"
            workspace.mkdir()
            ingest(str(source), workspace)
            ledger = create_plan(workspace)
            self.assertEqual(len(ledger["units"]), 2)
            self.assertEqual(ledger["units"][1]["product"], PRODUCT_SOLUTIONS)
            self.assertEqual(ledger["units"][0]["profile"], "MATEMATICA")
            queries = read_json(workspace / "ledgers" / "search_queries.json")
            self.assertEqual(queries["search_scope"], "GLOBAL_OPEN")
            self.assertEqual(queries["target_audio_languages"], ["pt", "en"])
            self.assertGreaterEqual(len(queries["seed_languages"]), 30)
            self.assertEqual(queries["queries"], [])

    def test_programming_and_portuguese_profiles_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "mix.md"
            source.write_text(
                "# Algoritmo Python\nImplemente código e teste a saída.\n\n# Literatura\nAnalise a figura de linguagem no poema.",
                encoding="utf-8",
            )
            workspace = base / "workspace"
            workspace.mkdir()
            ingest(str(source), workspace)
            ledger = create_plan(workspace)
            self.assertEqual(ledger["units"][0]["profile"], "COMPUTACAO")
            self.assertEqual(ledger["units"][1]["profile"], "LINGUAS_LITERATURA")

    def test_refined_map_rejects_nested_autoapproval(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace = base / "workspace"
            workspace.mkdir()
            ingest("álgebra linear", workspace)
            ledger = create_plan(workspace)
            manifest = read_json(workspace / "ingest" / "source_manifest.json")
            refined = copy.deepcopy(ledger)
            refined["units"][0]["verification_state"] = "VERIFIED_BY_AGENT"
            refined["units"][0]["notes"] = {"classification": "EXATO"}
            with self.assertRaisesRegex(ValueError, "autoaprovação"):
                validate_refined_map(refined, manifest)

    def test_refined_map_recalculates_temporary_unit_id(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace = base / "workspace"
            workspace.mkdir()
            ingest("geometria analítica", workspace)
            ledger = create_plan(workspace)
            manifest = read_json(workspace / "ingest" / "source_manifest.json")
            refined = copy.deepcopy(ledger)
            refined["units"][0]["verification_state"] = "VERIFIED_BY_AGENT"
            refined["units"][0]["unit_id"] = "TEMP-FLASHLIST-42"
            validated = validate_refined_map(refined, manifest)
            self.assertRegex(validated["units"][0]["unit_id"], r"^U-[0-9a-f]{12}$")
            self.assertNotEqual(validated["units"][0]["unit_id"], "TEMP-FLASHLIST-42")

    def test_refined_map_rejects_locator_outside_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace = base / "workspace"
            workspace.mkdir()
            ingest("geometria analítica", workspace)
            ledger = create_plan(workspace)
            manifest = read_json(workspace / "ingest" / "source_manifest.json")
            refined = copy.deepcopy(ledger)
            refined["units"][0]["verification_state"] = "VERIFIED_BY_HUMAN"
            refined["units"][0]["source_locators"] = [
                "/arquivo/externo-nao-inventariado.pdf#page=4"
            ]
            with self.assertRaisesRegex(ValueError, "não inventariada"):
                validate_refined_map(refined, manifest)

    def test_non_source_language_never_reuses_portuguese_title_blindly(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace = base / "workspace"
            workspace.mkdir()
            ingest("# Exercício de caixas vazias\nResolva e confira.", workspace)
            ledger = create_plan(workspace)
            unit = ledger["units"][0]
            identity = unit["search_identity"]
            identity["source_language"] = "pt"
            ledger["map_state"] = "V1_VERIFIED"
            queries = build_queries(ledger)
            japanese = next(row for row in queries["queries"] if row["language"] == "ja")
            self.assertFalse(japanese["execution_ready"])
            self.assertNotIn(unit["title"], japanese["query"])
            self.assertEqual(japanese["strategy"], "LOCALIZATION_REQUIRED")

    def test_bibliographic_anchor_is_language_neutral_and_executable(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace = base / "workspace"
            workspace.mkdir()
            ingest("# Título traduzível\nResolva o exercício.", workspace)
            ledger = create_plan(workspace)
            identity = ledger["units"][0]["search_identity"]
            identity.update(
                {
                    "source_language": "pt",
                    "creator": "Joseph Blitzstein",
                    "work": "Introduction to Probability",
                    "chapter": "Chapter 4",
                    "exercise": "Exercise 31",
                }
            )
            ledger["map_state"] = "V1_VERIFIED"
            japanese = next(
                row
                for row in build_queries(ledger)["queries"]
                if row["language"] == "ja"
                and row["execution_ready"]
            )
            self.assertTrue(japanese["execution_ready"])
            self.assertIn("Blitzstein", japanese["query"])
            self.assertIn("31", japanese["query"])
            self.assertNotIn("Introduction to Probability", japanese["query"])
            self.assertNotIn("Exercise", japanese["query"])
            self.assertNotIn("Título traduzível", japanese["query"])

    def test_foreign_query_does_not_treat_work_title_as_neutral_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace = base / "workspace"
            workspace.mkdir()
            ingest("# Caixas vazias\nResolva o problema e confira.", workspace)
            ledger = create_plan(workspace)
            identity = ledger["units"][0]["search_identity"]
            identity.update(
                {
                    "source_language": "pt",
                    "work": "Notas de Probabilidade em Português",
                    "chapter": "Capítulo sem número",
                    "exact_phrases": ["problema de caixas vazias"],
                    "technical_terms": ["caixas vazias"],
                }
            )
            ledger["map_state"] = "V1_VERIFIED"
            japanese = [
                row
                for row in build_queries(ledger)["queries"]
                if row["language"] == "ja"
            ]
            self.assertTrue(japanese)
            self.assertTrue(all(not row["execution_ready"] for row in japanese))
            self.assertTrue(
                all("Notas de Probabilidade" not in row["query"] for row in japanese)
            )

    def test_localized_terms_make_foreign_query_executable_without_hybrid_locator(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            workspace = base / "workspace"
            workspace.mkdir()
            ingest("# Caixas vazias\nResolva o exercício e confira.", workspace)
            ledger = create_plan(workspace)
            identity = ledger["units"][0]["search_identity"]
            identity.update(
                {
                    "source_language": "pt",
                    "work": "Notas de Probabilidade",
                    "exercise": "Exercício 12",
                    "localized_terms": [
                        {"language": "ja", "terms": ["空き箱問題"]}
                    ],
                }
            )
            ledger["map_state"] = "V1_VERIFIED"
            ready = [
                row
                for row in build_queries(ledger)["queries"]
                if row["language"] == "ja" and row["execution_ready"]
            ]
            self.assertTrue(ready)
            self.assertTrue(any("空き箱問題" in row["query"] for row in ready))
            self.assertTrue(all("Exercício" not in row["query"] for row in ready))

    def test_exact_exercise_query_keeps_number_and_drops_bibliographic_noise(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            _, ledger = self._verified_two_unit_workspace(base)
            ledger["units"][1]["product"] = PRODUCT_SOLUTIONS
            identity = ledger["units"][1]["search_identity"]
            identity.update(
                {
                    "source_language": "en",
                    "creator": "Joseph K. Blitzstein; Jessica Hwang",
                    "work": "Introduction to Probability",
                    "edition": "Second Edition, 2019",
                    "chapter": "Chapter 4 — Expectation",
                    "section": "4.12 Exercises",
                    "exercise": "61",
                    "exact_phrases": ["For X ~ Pois(lambda), find E(X!)"],
                    "notation": ["E(X!)"],
                    "technical_terms": ["Poisson expected factorial"],
                }
            )
            rows = [
                row
                for row in build_queries(ledger)["queries"]
                if row["unit_id"] == ledger["units"][1]["unit_id"]
                and row["language"] == "en"
            ]
            exact_rows = [
                row for row in rows if row["search_stage"] == "EXACT_OBJECT"
            ]
            self.assertGreaterEqual(len(exact_rows), 2)
            for exact in exact_rows:
                if exact["strategy"] == "EXACT_OBJECT_MINIMAL":
                    continue
                self.assertIn("Exercise 61", exact["query"])
                self.assertNotIn("Second Edition, 2019", exact["query"])
                self.assertLessEqual(len(exact["query"]), 280)
            strict = next(
                row
                for row in exact_rows
                if row["strategy"] not in {
                    "SOURCE_ECOSYSTEM_DISCOVERY",
                    "EXACT_OBJECT_MINIMAL",
                }
            )
            self.assertIn("E(X!)", strict["query"])
            minimal = next(
                row
                for row in exact_rows
                if row["strategy"] == "EXACT_OBJECT_MINIMAL"
            )
            self.assertEqual(minimal["query"], "For X ~ Pois(lambda), find E(X!)")
            self.assertNotIn("Blitzstein", minimal["query"])
            self.assertNotIn("Exercise 61", minimal["query"])
            self.assertNotIn("step by step", minimal["query"])
            self.assertNotIn('"', minimal["query"])
            self.assertEqual(exact_rows[0]["strategy"], "EXACT_OBJECT_MINIMAL")

    def test_theory_uses_unquoted_official_ecosystem_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            _, ledger = self._verified_two_unit_workspace(base)
            identity = ledger["units"][0]["search_identity"]
            identity.update(
                {
                    "source_language": "en",
                    "creator": "Joseph K. Blitzstein",
                    "work": "Introduction to Probability",
                    "section": "4.1",
                    "exact_phrases": ["Definition of expectation"],
                    "technical_terms": ["expected value"],
                    "official_domains": ["stat110.net"],
                }
            )
            rows = [
                row
                for row in build_queries(ledger)["queries"]
                if row["unit_id"] == ledger["units"][0]["unit_id"]
                and row["language"] == "en"
                and row["search_stage"] == "EXACT_OBJECT"
            ]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["strategy"], "SOURCE_ECOSYSTEM_DISCOVERY")
            self.assertIn("stat110", row["query"])
            self.assertIn("Definition of expectation", row["query"])
            self.assertNotIn('"Definition of expectation"', row["query"])
            self.assertNotIn("4.1", row["query"])

    def test_generic_theory_discovery_drops_mixed_bibliographic_noise(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            _, ledger = self._verified_two_unit_workspace(base)
            unit = ledger["units"][0]
            identity = unit["search_identity"]
            identity.update(
                {
                    "source_language": "pt",
                    "creator": "Autora Brasileira; Foreign Author",
                    "work": "Apostila em Português; English Textbook",
                    "localized_terms": [
                        {
                            "language": "en",
                            "terms": [
                                "maximum likelihood estimation",
                                "likelihood examples",
                            ],
                        }
                    ],
                }
            )
            ledger["map_state"] = "V1_VERIFIED"
            rows = [
                row
                for row in build_queries(ledger)["queries"]
                if row["unit_id"] == unit["unit_id"]
                and row["language"] == "en"
                and row["search_stage"] == "EXACT_OBJECT"
            ]
            self.assertEqual(len(rows), 1)
            query = rows[0]["query"]
            self.assertIn("maximum likelihood estimation", query)
            self.assertNotIn("Autora", query)
            self.assertNotIn("Apostila", query)

    def test_solution_equivalent_uses_structural_term_without_book_noise(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            _, ledger = self._verified_two_unit_workspace(base)
            unit = ledger["units"][1]
            unit["product"] = PRODUCT_SOLUTIONS
            identity = unit["search_identity"]
            identity.update(
                {
                    "source_language": "en",
                    "creator": "Morris DeGroot",
                    "work": "Probability and Statistics",
                    "exercise": "Exercises 1–7",
                    "localized_terms": [
                        {
                            "language": "en",
                            "terms": [
                                "DeGroot section 7.6 exercises 1 7 solutions",
                                "MLE invariance Poisson exponential normal",
                            ],
                        }
                    ],
                }
            )
            ledger["map_state"] = "V1_VERIFIED"
            equivalent = next(
                row
                for row in build_queries(ledger)["queries"]
                if row["unit_id"] == unit["unit_id"]
                and row["language"] == "en"
                and row["search_stage"] == "RIGOROUS_EQUIVALENT"
            )
            self.assertIn("MLE invariance Poisson exponential normal", equivalent["query"])
            self.assertNotIn("Probability and Statistics", equivalent["query"])
            self.assertNotIn("Exercises 1–7", equivalent["query"])

    def test_query_order_covers_all_exact_units_before_equivalents(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            _, ledger = self._verified_two_unit_workspace(base)
            for unit in ledger["units"]:
                unit["search_identity"]["source_language"] = "pt"
                unit["search_identity"]["technical_terms"] = [unit["title"]]
            rows = [
                row
                for row in build_queries(ledger)["queries"]
                if row["language"] == "pt"
            ]
            exact_positions = [
                index for index, row in enumerate(rows)
                if row["search_stage"] == "EXACT_OBJECT"
            ]
            equivalent_positions = [
                index for index, row in enumerate(rows)
                if row["search_stage"] == "RIGOROUS_EQUIVALENT"
            ]
            self.assertTrue(exact_positions)
            if equivalent_positions:
                self.assertLess(max(exact_positions), min(equivalent_positions))

    def _verified_two_unit_workspace(self, base: Path) -> tuple[Path, dict]:
        source = base / "duas.md"
        source.write_text(
            "# Teoria\nDefina esperança e dê exemplo.\n\n"
            "# Exercise\nSolve the exercise step by step and verify the answer.",
            encoding="utf-8",
        )
        workspace = base / "workspace"
        workspace.mkdir()
        ingest(str(source), workspace)
        draft = create_plan(workspace)
        refined = copy.deepcopy(draft)
        for unit in refined["units"]:
            unit["verification_state"] = "VERIFIED_BY_HUMAN"
        path = base / "map.json"
        atomic_write_json(path, refined)
        return workspace, import_map(workspace, path)


if __name__ == "__main__":
    unittest.main()
