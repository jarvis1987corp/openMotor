# Отчёт второго этапа локализации

Проверено в облачном Linux-средстве разработки, Python 3.12, PyQt6/Qt6,
с зависимостями из uv.lock и QT_QPA_PLATFORM=offscreen. Windows-сборка здесь
не запускалась. Изменения ограничены локализацией и необходимой компоновкой
длинных русских подписей.

## Покрытие

Каталог openmotor_ru.ts содержит **404 активные записи** (ключ — контекст,
английский source и комментарий для различения значений):

- **382 записи переведены** на русский;
- **22 записи намеренно совпадают с английским source** и имеют translatorcomment;
- **0 unfinished**, **0 obsolete/vanished**, **0 пустых переводов**;
- переводимые прикладные записи покрыты на **100% (382/382)**;
- доля записей с изменённым текстом среди всех записей — **94,55% (382/404)**;
- все **404/404** записи завершены и включены в .qm.

Проверена свежая выгрузка pylupdate6 из app.py, uilib, motorlib и mathlib.
Она совпадает с каталогом, включая все **14 Qt Designer форм**. Дополнительно
проверены ручные вызовы отображения текста, Property.dispName, все геометрии,
EnumProperty, инструменты, конвертеры, алерты, оси и легенды matplotlib.
Непереведённых собственных интерфейсных фраз за пределами перечисленных
исключений при этом аудите не найдено. Это покрытие прикладного каталога,
а не оценка текстов операционной системы или сторонних библиотек.

## Архитектура и совместимость

Существующий TranslationManager/QTranslator сохранён. Английский source остаётся
каноническим; язык хранится как en/ru в preferences.yaml. Старые preferences
используют en. Смена языка не меняет QLocale и выбранные единицы.

Добавлен Qt-независимый motorlib.localization.DisplayText: английская строка
сохраняет контекст, исходный шаблон и аргументы. display_text в UI переводит
шаблон, затем подставляет аргументы. Это позволяет обновлять уже вычисленные
алерты, не переводя готовую строку с числами. Подписи не входят в сохранённые
значения свойств. Ключи props, geomName/grainTypes, enum, единицы и имена топлива
сохраняют свои исходные значения; комбобоксы читают itemData/currentData.

LanguageChange обновляет подписи существующих редакторов, результаты, таблицы,
предупреждения и графики. Данные, масштаб, выбор каналов/шашек, положение
ползунка и несохранённые значения сохраняются. Расчёт двигателя и генерация
геометрии повторно не выполняются. Экспорт изображения создаёт отдельную
фигуру и сохраняет живой график.

Машинные CSV-заголовки, ENG, XML BurnSim и .ric не локализованы. Их структура,
значения, форматирование чисел, расширения и идентификаторы сохранены.

## Результаты проверки

| Проверка | Результат |
| --- | --- |
| Существующий test/unit.py | 37/37 пройдено |
| test/localization, включая тесты первого этапа | 35/35 пройдено |
| English → Русский → English | Пройдено для существующих и новых виджетов |
| Сохранение языка, старые preferences, отмена изменений | Пройдено |
| Все редакторы параметров, геометрии, enum и инструменты | Значения и идентификаторы сохранены |
| Уже выполненная симуляция, графики и preview | Перерасчёт запрещён тестами; данные/линии/масштаб сохранены |
| Все 18 существующих .ric примеров | Модель, каждый отсчёт каналов и английские алерты точно совпадают с исходным кодом staging |
| CSV / ENG / BurnSim и сохранённый .ric | Побайтно совпадают со снимком принятого первого этапа на каждом языке |
| ENG Append / Overwrite, импорт BurnSim | Стабильные режимы и одинаковый импорт на всех языках |
| .ts против новой выгрузки, .qm против каждой записи .ts | Пройдено |
| placeholders, URL, расширения, Kn/ISP/Isp/c* | Проверка каталога пройдена |
| Вычислительная структура AST моделей | 23 файла совпадают после удаления маркеров локализации; исключён только текст KeyError |
| Критический ruff (как в CI) | Пройдено |
| E/F/I для новых модулей и тестов | Пройдено |
| git diff --check | Пройдено |
| Визуальный просмотр основного окна, Preferences и редактора сопла | Пройдено в offscreen/Fusion |

Команды воспроизведения находятся в README.md. Эталонные SHA-256 и описание
их происхождения — в test/localization/data. Полные каналы сравниваются без
округления или допуска, который мог бы скрыть изменение расчёта.

Старый test/compare.py также выполнен для **18 сценариев** через временный
адаптер, добавляющий yaml.FullLoader без изменения файлов репозитория.
Это информационный скрипт без утверждений pass/fail. Его исторические эталоны
относятся к версии 0.4.0: он показывает расхождения статистики, дополнительные
предупреждения об отрыве потока и отличие 2.000 от 2.0 в тексте алерта.
У real-сценариев отличие от измерений достигает 13,581%; это не ошибка,
появившаяся из-за локализации: все 18 моделей, каналы и алерты отдельно
сравнены с исходным staging и совпали точно. Сам скрипт требует адаптера
для установленного PyYAML и вызывает Windows-команду color в Linux.

## Намеренно оставлено без перевода

22 записи каталога:

- BATES, Finocyl — общепринятые имена геометрий;
- openMotor — название приложения;
- Kn — два контекста параметров и результатов; ISP: — физическое обозначение;
- ↑, ↓, <, >, -, 1/1 — символы/числовые индикаторы (знак - в двух контекстах);
- Ctrl+Q, Ctrl+O, Ctrl+S, Ctrl+R, Ctrl+P, Ctrl+N, Ctrl+Z, Ctrl+Y,
  Ctrl+Shift+S — сочетания клавиш.

За пределами каталога сохранены:

- единицы, физические обозначения/формулы, числа, обозначения двигателей,
  включая N/A при отсутствии класса импульса;
- английские программные ключи, enum, geomName и машинные поля экспорта;
- имена топлива из библиотеки, пользовательские имена/пути, названия DXF-сущностей;
- New Propellant и суффикс (Copy) как исходные **имена записей библиотеки**,
  которые пользователь может редактировать; они используются как идентичность данных;
- English / Русский как собственные названия языков;
- y/n — стабильные ключи ввода в командной строке;
- диагностические сообщения в журнале разработчика;
- исходные подробности неизвестных исключений ОС, YAML, DXF, SciPy/NumPy и Qt.
  Прикладные заголовки и пояснения этих диалогов переведены.

## Термины для решения пользователя

Ни один спорный термин не блокирует работу. Для проверки терминологии сохранено
английское обозначение рядом с русским:

| Термин | Текущий вариант | Что уточнить |
| --- | --- | --- |
| Web | Толщина горящего свода (Web) | Предпочтительный короткий вариант для каналов и параметров |
| Fin / Fins у Finocyl | Ребро (Fin) / рёбра (Fins) | Единый термин для ответвления канала и инвертированного выступа: ребро, паз или иной принятый вариант |
| Inverted fins | Инвертированные рёбра (Inverted fins) | Название выступов топлива в канале |
| Top / Bottom для inhibited ends | Верхний (Top) / Нижний (Bottom) | Оставить экранные направления или выбрать передний/задний торец |
| Moon Burner | Эксцентричный канал (Moon Burner) | Оставить этот вариант или собственное принятое название |
| Rod and Tube, C/D Grain, X Core | Русское описание + исходное имя | Утвердить предпочитаемые названия геометрий |
| Tablet / Pie Segment | Таблетка (Tablet) / Сектор (Pie Segment) | Названия неподдерживаемых геометрий в предупреждениях импорта |

Thrust, Chamber Pressure, Burn Time, Total Impulse, Specific Impulse, Burn Rate,
Characteristic Velocity, Propellant Grain, Nozzle и Throat используют одну
терминологию; символы ISP/Isp, Kn и c* не изменены.

## Обнаруженные проблемы

Обрезание длинных русских каналов исправлено: снят предел ширины 220 px,
панель рассчитывает минимальную ширину по содержимому. Две длинные подписи
статистики переносятся; высота группы может увеличиваться. Полные предупреждения
доступны в tooltips, таблица подбирает высоту строк.

Старый экспорт PNG очищал живую фигуру, из-за чего последующее LanguageChange
теряло график. Теперь экспорт использует отдельную фигуру; добавлен тест.

Регрессий локализации после исправлений не обнаружено. Остались существующие
предупреждения решателя сопла SciPy/NumPy (деление на ноль, sqrt, fsolve) и
предупреждение QLayout при создании некоторых редакторов. Они не скрываются;
эталоны и тесты подтверждают прежнее поведение. Физические формулы не менялись.

## Ручная проверка Windows

1. Собрать и запустить обе PyInstaller-конфигурации Windows; проверить загрузку
   openmotor_ru.qm и официального qtbase_ru.qm рядом с приложением.
2. Проверить размеры окон, переносы, вкладки preview и длинные параметры при
   масштабировании 100%, 125%, 150% и 200%, со светлой и тёмной темой.
3. Проверить системные диалоги открытия/сохранения и Qt-кнопки: нативные диалоги
   могут брать язык из Windows, а не из прикладного QTranslator.
4. Переключить язык при открытых Preferences, редакторе топлива, инструменте,
   диалоге экспорта и уже вычисленных результатах; проверить выбор и ввод.
5. Перезапустить приложение с ru, затем en; загрузить/сохранить старый проект,
   проверить пути с кириллицей и экспорты в реальных BurnSim/RASP-потребителях.
6. Просмотреть сохранённый PNG на русском: шрифт, оси и длинные легенды.
7. Утвердить перечисленные выше специализированные термины.

Следующие функции и Design Assistant в рамках этого этапа не добавлялись.

## Изменённые и добавленные файлы второго этапа

Список ниже относится к снимку принятого первого этапа. Уже существовавшие
изменения Preferences.ui и About первого этапа сохранены. В правилах упаковки
добавлено включение нового отчёта .md. Сгенерированные *_ui.py регенерированы из форм и не
редактировались вручную.

Изменены (67):

```text
MANIFEST.in
app.py
mathlib/_find_perimeter.py
motorlib/grain.py
motorlib/grains/bates.py
motorlib/grains/cGrain.py
motorlib/grains/conical.py
motorlib/grains/custom.py
motorlib/grains/dGrain.py
motorlib/grains/finocyl.py
motorlib/grains/moonBurner.py
motorlib/grains/rodTube.py
motorlib/grains/star.py
motorlib/grains/xCore.py
motorlib/motor.py
motorlib/nozzle.py
motorlib/propellant.py
motorlib/simResult.py
motorlib/units.py
scripts/translations.py
setup.py
test/localization/test_localization.py
uilib/converter.py
uilib/converters/burnsimExporter.py
uilib/converters/burnsimImporter.py
uilib/converters/csvExporter.py
uilib/converters/engExporter.py
uilib/converters/imageExporter.py
uilib/fileIO.py
uilib/fileManager.py
uilib/importExportManager.py
uilib/localization.py
uilib/preferencesManager.py
uilib/propellantManager.py
uilib/tool.py
uilib/toolManager.py
uilib/tools/changeDiameter.py
uilib/tools/expansion.py
uilib/tools/initialKN.py
uilib/tools/maxKN.py
uilib/tools/maxPressure.py
uilib/tools/neutralBates.py
uilib/tools/nozzleCoeff.py
uilib/translations/README.md
uilib/translations/openmotor_ru.qm
uilib/translations/openmotor_ru.ts
uilib/views/forms/MainWindow.ui
uilib/views/forms/ResultsWidget.ui
uilib/widgets/burnrateGraph.py
uilib/widgets/channelSelector.py
uilib/widgets/collectionEditor.py
uilib/widgets/grainPreviewWidget.py
uilib/widgets/grainSelector.py
uilib/widgets/graphWidget.py
uilib/widgets/mainWindow.py
uilib/widgets/motorEditor.py
uilib/widgets/nozzlePreviewWidget.py
uilib/widgets/polygonEditor.py
uilib/widgets/propellantMenu.py
uilib/widgets/propellantPressureGraph.py
uilib/widgets/propellantPreviewWidget.py
uilib/widgets/propellantTabEditor.py
uilib/widgets/propertyEditor.py
uilib/widgets/resultsWidget.py
uilib/widgets/simulationAlertsDialog.py
uilib/widgets/simulationProgressDialog.py
uilib/widgets/tabularEditor.py
```

Добавлены (5):

```text
motorlib/localization.py
test/localization/data/README.md
test/localization/data/model-reference.json
test/localization/data/stage1-reference.json
uilib/translations/AUDIT.md
```
