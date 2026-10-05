"""Qt translation lifecycle. English source strings remain the fallback."""

import logging
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QEvent, QLibraryInfo, QObject, QTranslator, pyqtSignal

from motorlib.localization import QT_TRANSLATE_NOOP, DisplayText

DEFAULT_LANGUAGE = "en"
LANGUAGES = (("en", "English"), ("ru", "Русский"))
TRANSLATIONS_PATH = Path(__file__).resolve().parent / "translations"

# These source strings describe stable identities; they are never model keys.
GEOMETRY_LABELS = {
    'BATES': QT_TRANSLATE_NOOP('GrainGeometry', 'BATES'),
    'C Grain': QT_TRANSLATE_NOOP('GrainGeometry', 'C Grain'),
    'Conical': QT_TRANSLATE_NOOP('GrainGeometry', 'Conical'),
    'Custom Grain': QT_TRANSLATE_NOOP('GrainGeometry', 'Custom Grain'),
    'D Grain': QT_TRANSLATE_NOOP('GrainGeometry', 'D Grain'),
    'End Burner': QT_TRANSLATE_NOOP('GrainGeometry', 'End Burner'),
    'Finocyl': QT_TRANSLATE_NOOP('GrainGeometry', 'Finocyl'),
    'Moon Burner': QT_TRANSLATE_NOOP('GrainGeometry', 'Moon Burner'),
    'Rod and Tube': QT_TRANSLATE_NOOP('GrainGeometry', 'Rod and Tube'),
    'Star Grain': QT_TRANSLATE_NOOP('GrainGeometry', 'Star Grain'),
    'X Core': QT_TRANSLATE_NOOP('GrainGeometry', 'X Core'),
    'Star': QT_TRANSLATE_NOOP('GrainGeometry', 'Star'),
    'Tablet': QT_TRANSLATE_NOOP('GrainGeometry', 'Tablet'),
    'Pie Segment': QT_TRANSLATE_NOOP('GrainGeometry', 'Pie Segment'),
}
ENUM_LABELS = {
    'Neither': QT_TRANSLATE_NOOP('PropertyChoices', 'Neither'),
    'Top': QT_TRANSLATE_NOOP('PropertyChoices', 'Top'),
    'Bottom': QT_TRANSLATE_NOOP('PropertyChoices', 'Bottom'),
    'Both': QT_TRANSLATE_NOOP('PropertyChoices', 'Both'),
    'Append': QT_TRANSLATE_NOOP('PropertyChoices', 'Append'),
    'Overwrite': QT_TRANSLATE_NOOP('PropertyChoices', 'Overwrite'),
}


def display_text(text):
    """Translate marked text at the UI boundary, before formatting its values."""
    if isinstance(text, DisplayText):
        translated = QCoreApplication.translate(text.context, text.source)
        args = tuple(display_text(value) if isinstance(value, DisplayText) else value for value in text.args)
        kwargs = {key: display_text(value) if isinstance(value, DisplayText) else value
                  for key, value in text.kwargs.items()}
        return translated.format(*args, **kwargs) if args or kwargs else translated
    return '' if text is None else str(text)


def geometry_name(identity):
    return display_text(GEOMETRY_LABELS.get(identity, identity))


def enum_label(value):
    return display_text(ENUM_LABELS.get(value, value))


def update_alert_table(table, alerts):
    from PyQt6.QtWidgets import QTableWidgetItem

    from motorlib.simResult import alertLevelNames, alertTypeNames

    table.setRowCount(len(alerts))
    for row, alert in enumerate(alerts):
        texts = (alertLevelNames[alert.level], alertTypeNames[alert.type], alert.location, alert.description)
        for column, text in enumerate(texts):
            item = table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                table.setItem(row, column, item)
            item.setText(display_text(text))
            item.setToolTip(display_text(text))
    table.resizeRowsToContents()


def update_alert_list(widget, alerts):
    """Retain selection and make long diagnostics readable through tooltips."""
    while widget.count() > len(alerts):
        widget.takeItem(widget.count() - 1)
    for row, alert in enumerate(alerts):
        text = display_text(alert.description)
        if row >= widget.count():
            widget.addItem(text)
        widget.item(row).setText(text)
        widget.item(row).setToolTip(text)


class TranslatedForm:
    """LanguageChange support for forms with no dynamic output placeholders."""

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, 'ui'):
            self.ui.retranslateUi(self)
        super().changeEvent(event)


def normalize_language(language):
    """Accept stable language codes only, including when reading old preferences."""
    return language if isinstance(language, str) and language in dict(LANGUAGES) else DEFAULT_LANGUAGE


class TranslationManager(QObject):
    """Own QTranslators for as long as they are installed on the application.

    Selecting a language does not change QLocale, model values, or unit formats.
    Missing application catalogs fall back to English; missing Qt catalogs are
    reported while the application catalog can still be used.
    """

    languageChanged = pyqtSignal(str)

    def __init__(self, application, translations_path=None):
        super().__init__(application)
        self.application = application
        self.translations_path = Path(translations_path or TRANSLATIONS_PATH)
        self.language = DEFAULT_LANGUAGE
        self._translators = []

    def setLanguage(self, language):
        requested = normalize_language(language)
        if requested == self.language:
            return True

        translators = []
        if requested != DEFAULT_LANGUAGE:
            app_translator = QTranslator(self)
            if not app_translator.load(str(self.translations_path / f"openmotor_{requested}.qm")):
                logging.getLogger(__name__).warning("Cannot load %s translation; using English", requested)
                self.setLanguage(DEFAULT_LANGUAGE)
                return False

            qt_translator = QTranslator(self)
            qt_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
            # Frozen builds put the official Qt catalog beside our own catalog.
            if (qt_translator.load(str(self.translations_path / f"qtbase_{requested}.qm"))
                    or qt_translator.load(f"qtbase_{requested}", qt_path)):
                translators.append(qt_translator)
            else:
                logging.getLogger(__name__).warning("Cannot load Qt standard dialog translation for %s", requested)
            translators.append(app_translator)

        for translator in self._translators:
            self.application.removeTranslator(translator)
            translator.deleteLater()
        self._translators = translators
        for translator in self._translators:
            self.application.installTranslator(translator)
        self.language = requested
        self.languageChanged.emit(requested)
        return True
