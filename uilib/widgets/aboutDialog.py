from PyQt6.QtWidgets import QDialog, QApplication
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QPixmap
from ..views.AboutDialog_ui import Ui_AboutDialog
from ..resources import resource_path


class AboutDialog(QDialog):
    def __init__(self, version):
        QDialog.__init__(self)
        self.version = version
        self.ui = Ui_AboutDialog()
        self.ui.setupUi(self)
        self.ui.labelImage.setPixmap(QPixmap(resource_path('oMIconCyclesSmall.png')))

        self.setWindowIcon(QApplication.instance().icon)

        self.ui.labelText.setText(self.ui.labelText.text().replace('###', version))

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, 'ui'):
            self.ui.retranslateUi(self)
            self.ui.labelText.setText(self.ui.labelText.text().replace('###', self.version))
        super().changeEvent(event)
