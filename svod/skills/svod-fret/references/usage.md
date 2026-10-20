# Запуск необязательного FRET-пакета

Это исходники для явной локальной сборки, не опубликованный образ и не обязательный gate. Не требуется менять SVOD stores, pipelines или личный профиль агента. Найдите каталог `svod/skills/svod-fret` в checkout или установленном Python package; далее `<skill-dir>` — его абсолютный путь. При копировании skill явно копируйте весь этот каталог, не один SKILL.md. Автоматическая установка не выполняется.

## Команды

На хосте нужны Python 3.10+, Git и запущенный Docker daemon. Node/Java/Z3/npm ставятся только внутрь образа. Через `terminal`:

    python3 <skill-dir>/scripts/launcher.py --help
    python3 <skill-dir>/scripts/launcher.py build
    python3 <skill-dir>/scripts/launcher.py smoke --output <new-smoke-directory>
    python3 <skill-dir>/scripts/launcher.py run <requirements.json> --output <new-output-dir>

Build требует сеть для GitHub, registry, apt и npm. Анализ запускается без сети, input read-only, без capabilities, с memory/pid limits. Это не аудит безопасности и не публичный сервис; используйте доверенные локальные требования. Образ содержит build tools и может занимать около 1 GB. Не запускайте npm install на хосте.

Build принимает `--cache-dir <directory>`; по умолчанию это `~/.cache/svod-fret`. Внешний timeout анализа фиксирован: 1800 секунд, затем launcher удаляет только собственный контейнер. Cache/runtime и output не должны находиться внутри установленного skill/site-packages. `--output` указывает новый каталог; предыдущие результаты не затираются. Удаление cache или локального образа выполняйте отдельно после проверки, что они не нужны; launcher не чистит чужие ресурсы.

REALIZABLE и UNREALIZABLE — оба окончательные ответы анализа и допускают exit 0. Это не PASS совместимости: автоматический потребитель обязан читать `report.json.status`. UNKNOWN и ERROR — неокончательные результаты с ненулевым exit; проверить raw логи. Нет скрытых retries. При явном повторении используйте новый output и учитывайте оба результата.

## Вход

Полные примеры: `examples/compatible/requirements.json`, `examples/conflict/requirements.json`, `examples/invalid/requirements.json`, `examples/waiting/requirements.json`.

- `project`, `component`: один компонент за анализ.
- `variables`: явные `name`, `role` Input/Output и `type` boolean/integer/double. Boolean-модели — реально упражняемый baseline; не обещать проверенность остальных типов.
- `requirements`: уникальный безопасный `id`, `description` — русский исходник и `text` — настоящий FRETish. Не используйте `assumption` в ID: upstream трактует это особо.
- `assumptions`: readable список абстракций/допущений. Он сохраняется в отчёте, но сам по себе не ограничивает solver input. Если нужен формальный environmental constraint, его моделирование требует отдельной проверки семантики; текст списка не становится формулой автоматически.
- `timeout`: лимит каждого solver query, не суммарного анализа. Внешний timeout launcher отдельно ограничивает весь контейнер.

Сохраняйте исходник, принятые уточнения человека и новую версию JSON до анализа. Не подменяйте неизвестное бизнес-правило удобной формулой.

## Артефакты

Откройте `report.html` обычным браузером; CLI-сессия отдаёт абсолютный путь, не attachment. `report.json` содержит нормализованный статус, исходные требования/допущения и provenance. `input.json` — фактически использованный вход. `requirements-analysis.json`, `*.formalize.log` и `*.svg` — настоящий compiler output; `summary.json`, `realizability.json`, `solver/`, `solver-invocations/` и логи контейнера сохраняют анализ, насколько он успел завершиться. ERROR может возникнуть до появления отдельных файлов; отсутствие evidence не равно успеху.

Native timing SVG — общий шаблон FRET, его конкретный смысл задаёт compiler legend/description рядом. Граф конфликта проецирует реальные conflict IDs, не является state machine. Solver counterexample существует только если его вернул analyzer; нет трассы — не рисуйте её как полученный результат. Авторские сценарии всегда отдельно помечаются как ожидаемое поведение.

## Пример ожидания и уточнение смысла

`examples/waiting/` — малый срез реального обсуждения требований SVOD. Ошибка — одноразовое событие, но обязанность ожидания сохраняется. Спорный случай: новая ошибка и разрешение продолжить пришли одновременно. Пользователь ранее выбрал приоритет новой ошибки; WAIT_STATE явно оставляет ожидание включённым. Исторический источник решения: store `svod-rnd`, `experiments/fretish/cases/svod-temporal/README.md`, раздел Accepted scope versus candidate decisions. Это ранее зафиксированный ответ человека, не новое открытие solver и не заявление о проверке реализации SVOD.

Срез не включает freshness, partial outcomes, completion bits, source readback или реальные команды. Один tick — граница наблюдения/диспетчеризации. В scope whole-trace pinned FRET выражение `!(at the previous occurrence of true, !awaiting_user)` означает предыдущий awaiting_user с начальным false; проверяйте сгенерированный Lustre при изменении scope/версии. Запуск примера проверяет совместимость этой формализации, не полноту исходного продукта.

## Закрепление и experimental readiness

Upstream FRET `cf0f913cc15c41705e803593297e89cd6056b839`; Node20.19.5 base digest, npm lock и SHA256 артефактов JKind закреплены в scripts. Исходный solver artifact release v2.2 может показывать banner `JRealizability 4.5.1-202311081135`: release label и runtime banner различаются. Java/Z3 pins смотрите в Dockerfile. Apt mirrors не snapshot-pinned, побитовая воспроизводимость и вечная доступность пакетов не обещаются.

Один исторический настоящий `Z3 terminated unexpectedly` не считается исправленным последующими зелёными запусками. При сохранении этой зависимости инструмент experimental: ручной просмотр статуса/raw evidence, без обещания надёжного CI gate. Информация о выполненных проверках должна ссылаться на текущий input digest/image ID, не выдавать старый output за новый запуск.

REALIZABLE не доказывает полноту требований, верность перевода замысла, безопасность контейнера или соответствие кода. По итогам анализа человек уточняет требования, а не обязан принимать предложенное агентом объяснение.

## Лицензии

Адаптеры распространяются по Apache-2.0 вместе с SVOD. FRET Apache-2.0 скачивается при build; полный upstream сохраняет LICENSE.pdf и attribution. См. `third-party.md`. Образ не публикуется этой задачей; публикация требует отдельной проверки third-party notices всех включённых зависимостей.
