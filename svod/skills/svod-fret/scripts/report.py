"""Render solver results without inventing behaviors or conflict explanations."""
import html
import json
import re
import sys
from pathlib import Path


def render(result):
    def esc(value):
        return html.escape(str(value), quote=True)
    status = result.get("status", "UNKNOWN")
    if status not in {"REALIZABLE", "UNREALIZABLE", "UNKNOWN", "ERROR"}:
        status = "UNKNOWN"
    description = {
        "REALIZABLE": "Требования реализуемы при заданной модели входов и допущениях.",
        "UNREALIZABLE": "Требования невозможно выполнить совместно при заданной модели входов.",
        "UNKNOWN": "Анализ не завершён: результат неизвестен.",
        "ERROR": "Анализ не завершён из-за ошибки инструмента.",
    }[status]
    requirements = result.get("requirements", [])
    title = esc(result.get("title") or "FRETish")
    project = esc(result.get("project", "Не указан"))
    assumptions = "".join(f'<li>{esc(item)}</li>' for item in result.get("assumptions", []))
    assumptions = f'<ul>{assumptions}</ul>' if assumptions else '<p>Допущения не предоставлены.</p>'
    rows = "".join(
        f'<article id="req-{esc(r["id"])}"><h3>{esc(r["id"])}</h3>'
        f'<h4>Русский исходник</h4><p>{esc(r.get("description") or "Не предоставлен.")}</p>'
        f'<h4>Исходный FRETish</h4><pre>{esc(r["text"])}</pre></article>'
        for r in requirements
    )
    conflicts = result.get("conflicts", [])
    graph_rows = []
    for index, group in enumerate(conflicts):
        y = 55 + index * 85
        labels = [str(item) for item in group]
        graph_rows.append(f'<text x="20" y="{y}">Конфликт {index + 1}</text>')
        for n, label in enumerate(labels):
            x = 160 + n * 150
            graph_rows.append(
                f'<line x1="115" y1="{y-5}" x2="{x}" y2="{y-5}" stroke="#e87979"/>'
                f'<rect x="{x}" y="{y-25}" width="130" height="40" rx="6" fill="#542d3b"/>'
                f'<text x="{x+10}" y="{y}">{esc(label)}</text>'
            )
    width = max([640] + [180 + 150 * len(g) for g in conflicts])
    height = max(110, 40 + len(conflicts) * 85)
    graph = (
        f'<svg role="img" aria-label="Conflict graph" viewBox="0 0 {width} {height}">'
        '<style>text{fill:#eee;font:16px sans-serif}</style>' + "".join(graph_rows) + '</svg>'
        if conflicts else '<p>Группы конфликтов не предоставлены. '
        'Их отсутствие не заменяет результат анализа.</p>'
    )
    native = []
    for item in result.get("semantics", []):
        rid = esc(item["id"])
        semantics = item["semantics"]
        diagram = (
            f'<img src="{rid}.svg" alt="Native FRET timing diagram {rid}">'
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", str(item["id"]))
            else '<p>Ссылка на диаграмму недоступна: некорректный ID.</p>'
        )
        native.append(f'<article><h3>{rid}: семантика FRET</h3>'
                      f'{diagram}'
                      '<h4>Легенда компилятора</h4>'
                      f'<pre>{esc(semantics.get("diagramVariables", {}))}</pre>'
                      f'<p>{esc(semantics.get("description", ""))}</p>'
                      '<details><summary>Raw семантика и формализация компилятора</summary>'
                      f'<pre>{esc(json.dumps(semantics, ensure_ascii=False, indent=2))}</pre>'
                      '</details></article>')
    traces = []
    for counterexample in result.get("counterexamples", []):
        traces.append('<article><h3>Контрпример solver</h3><pre>' +
                      esc(json.dumps(counterexample, ensure_ascii=False, indent=2)) +
                      '</pre></article>')
    if not traces:
        traces.append('<p>Контрпример не предоставлен. Трасса не восстанавливается '
                      'из шаблона SVG или графа конфликтов.</p>')
    provenance = esc(json.dumps(result.get("provenance", {}), ensure_ascii=False, indent=2))
    diagnostics = esc(json.dumps(result.get("diagnostics", []), ensure_ascii=False, indent=2))
    artifacts = ["input.json", "report.json", "summary.json", "requirements-analysis.json",
                 "realizability.json", "realizability.log", "container.log", "seed.log",
                 "solver/", "solver-invocations/"]
    artifacts.extend(str(r["id"]) + ".formalize.log" for r in requirements
                     if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", str(r["id"])))
    links = "".join(f'<li><a href="{esc(path)}">{esc(path)}</a></li>' for path in artifacts)
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<title>{title} — {status}</title>
<style>
body{{background:#141923;color:#e6edf5;font:17px system-ui;
max-width:1000px;margin:40px auto;padding:24px}}
article,section{{background:#202837;padding:16px;margin:16px 0;border-radius:10px}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere}}
svg{{width:100%}}h1{{color:#91baff}}a{{color:#91baff}}
</style>
<h1>{title} · {status}</h1><p>Проект: {project}</p><p>{description}</p>
<p>Этот отчёт показывает результат формального анализа, но не полноту требований,
соответствие замыслу пользователя или корректность кода.</p>
<section><h2>Допущения</h2>{assumptions}</section>
<section><h2>Карта конфликтов</h2>{graph}<p>Проекция ID групп из результата solver.
Это не диаграмма состояний и не контрпример исполнения.</p></section>
<h2>Требования: исходный замысел и формализация</h2>{rows}
<h2>Временные диаграммы</h2><p>Оригинальные шаблонные SVG FRET.
Конкретный смысл переменных указан в легенде; это не вычисленная трасса сценария.</p>
{''.join(native)}
<h2>Контрпримеры</h2>{''.join(traces)}
<section><h2>Происхождение</h2><pre>{provenance}</pre></section>
<section><h2>Диагностика</h2><pre>{diagnostics}</pre></section>
<section><h2>Сырые артефакты</h2><p>Локальные файлы при наличии;
ошибка или ранняя остановка могут оставить только часть артефактов.</p>
<ul>{links}</ul></section></html>'''


if __name__ == "__main__":
    data = json.loads(Path(sys.argv[1]).read_text())
    Path(sys.argv[2]).write_text(render(data), encoding="utf-8")
