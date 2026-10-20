"""Renderer unit fixtures are synthetic, never evidence of a solver run."""
import importlib.util
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render(result):
    path = ROOT / "svod/skills/svod-fret/scripts/report.py"
    spec = importlib.util.spec_from_file_location("fret_report", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render(result)


class ReportTests(unittest.TestCase):
    def test_statuses_are_distinct_and_never_claim_code_correctness(self):
        for status in ("REALIZABLE", "UNREALIZABLE", "UNKNOWN", "ERROR", "unexpected"):
            with self.subTest(status=status):
                page = render({"status": status})
                expected = "UNKNOWN" if status == "unexpected" else status
                self.assertIn(f"· {expected}", page)
                self.assertIn("не полноту", page)
                self.assertIn("или корректность кода", page)
                self.assertNotIn("Требования совместимы", page)

    def test_compiler_solver_and_metadata_content_are_text_not_markup(self):
        payload = '<script>"& user</script>'
        page = render({"title": payload, "project": payload, "assumptions": [payload],
                       "diagnostics": payload, "provenance": {"image": payload},
                       "requirements": [{"id": payload, "text": payload,
                                         "description": payload}],
                       "conflicts": [[payload]], "counterexamples": [{"value": payload}],
                       "semantics": [{"id": payload, "semantics": {
                           "description": payload, "diagramVariables": {"RR": payload},
                           "diagram": payload}}]})
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_graph_projects_only_actual_conflict_groups_not_all_requirements(self):
        page = render({"status": "UNREALIZABLE", "conflicts": [["R1", "R2"]],
                       "requirements": [{"id": rid, "text": "synthetic fixture"}
                                        for rid in ("R1", "R2", "R3")]})
        graph = page.split('<svg', 1)[1].split('</svg>', 1)[0]
        self.assertIn("R1", graph)
        self.assertIn("R2", graph)
        self.assertNotIn("R3", graph)
        self.assertIn("не контрпример исполнения", page)

    def test_native_compiler_formalization_is_preserved_without_fabricating_a_trace(self):
        page = render({"status": "UNREALIZABLE", "requirements": [], "conflicts": [],
                       "semantics": [{"id": "R1", "semantics": {
                           "diagramVariables": {"RR": "готовность <сигнал>"},
                           "description": "Описание <compiler>",
                           "ft": "G (request -> F ready)"}}]})
        for text in ("G (request -&gt; F ready)", "готовность &lt;сигнал&gt;",
                     "Описание &lt;compiler&gt;", "Легенда компилятора",
                     "Контрпример не предоставлен"):
            self.assertIn(text, page)
        self.assertNotIn("Step 0", page)
        self.assertNotIn("<svg", page)

    def test_requirement_ids_cannot_turn_local_artifacts_into_external_urls(self):
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.urls = []

            def handle_starttag(self, tag, attrs):
                self.urls.extend(value for key, value in attrs if key in {"src", "href"})

        parser = Links()
        for rid in ('javascript:alert(1)', '//evil.test/x', '../outside', 'R" onclick="bad'):
            page = render({"requirements": [{"id": rid, "text": "raw"}],
                           "semantics": [{"id": rid, "semantics": {}}]})
            parser.feed(page)
        for url in parser.urls:
            self.assertNotIn(":", url)
            self.assertNotIn("../", url)
            self.assertFalse(url.startswith("//"))
            self.assertNotIn('"', url)

    def test_error_diagnostics_and_local_raw_artifact_links_are_available(self):
        page = render({"status": "ERROR", "diagnostics": {"message": "solver <crashed>"},
                       "requirements": [{"id": "R1", "text": "bad input"}]})
        self.assertIn("solver &lt;crashed&gt;", page)
        self.assertIn("Диагностика", page)
        for path in ("input.json", "report.json", "summary.json", "requirements-analysis.json",
                     "realizability.json", "realizability.log", "container.log", "seed.log",
                     "solver/", "solver-invocations/", "R1.formalize.log"):
            self.assertIn(f'href="{path}"', page)
        self.assertIn("при наличии", page)

    def test_russian_source_assumptions_and_raw_fretish_remain_distinct(self):
        page = render({"status": "REALIZABLE", "title": "Проверка <замысла>",
                       "project": "Тест & проект", "assumptions": ["Вход <доверенный>"],
                       "requirements": [{"id": "R1", "description": "Ждать <ответ>",
                                         "text": "controller shall satisfy ready"}]})
        for text in ("Проверка &lt;замысла&gt;", "Тест &amp; проект", "Допущения",
                     "Вход &lt;доверенный&gt;", "Русский исходник", "Ждать &lt;ответ&gt;",
                     "Исходный FRETish", "controller shall satisfy ready"):
            self.assertIn(text, page)
        self.assertLess(page.index("Ждать &lt;ответ&gt;"),
                        page.index("controller shall satisfy ready"))

    def test_legacy_fixture_remains_readable_and_escaped(self):
        page = render({"status": "UNREALIZABLE", "requirements": [
            {"id": "R1", "text": '<script>alert("x")</script>'}],
            "conflicts": [["R1"]], "counterexamples": [{"Step 0": False}],
            "semantics": [{"id": "R1", "semantics": {
                "diagramVariables": {"RR": "active"}, "description": "active must hold"}}]})
        for text in ("UNREALIZABLE", "R1.svg", "Step 0", "active must hold", "&lt;script&gt;"):
            self.assertIn(text, page)
        self.assertNotIn('<script>alert("x")</script>', page)
        self.assertIn("не диаграмма состояний", page)
        self.assertIn("не вычисленная трасса", page)


if __name__ == "__main__":
    unittest.main()
