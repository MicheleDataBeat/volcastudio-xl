"""Small layout helpers shared by the Desktop App's sections."""
from PySide6 import QtCore, QtWidgets as W


class FlowLayout(W.QLayout):
    """Natural-size controls that wrap to the next line instead of overflowing.

    Fonts differ between platforms; a row that fits on Linux can be wider on
    Windows. Wrapping keeps every control reachable without horizontal scrolling.
    """
    def __init__(self, spacing=6):
        super().__init__()
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return QtCore.Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QtCore.QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, False)

    def sizeHint(self):
        # The unwrapped row. (Returning the minimum, as Qt's example does, makes
        # a parent layout compute heightForWidth at a tiny width and inflate.)
        width = sum(item.sizeHint().width() for item in self.items) + max(0, len(self.items) - 1) * self.spacing()
        height = max((item.sizeHint().height() for item in self.items), default=0)
        margins = self.contentsMargins()
        return QtCore.QSize(width + margins.left() + margins.right(), height + margins.top() + margins.bottom())

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QtCore.QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def arrange(self, rect, test_only):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        for item in self.items:
            hint = item.sizeHint()
            if line_height and x + hint.width() > area.right() + 1:
                x, y, line_height = area.x(), y + line_height + self.spacing(), 0
            if not test_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class SampleList(W.QListWidget):
    """A small size hint: in a scrolling section the list takes the leftover height."""
    def sizeHint(self):
        return QtCore.QSize(256, 96)


class SampleListView(W.QListView):
    """The model-based twin of SampleList for the library listing."""
    def sizeHint(self):
        return QtCore.QSize(256, 96)


def flow_row(layout, *widgets):
    """Add a wrapping row of natural-size widgets to a box layout."""
    row = FlowLayout()
    for widget in widgets:
        row.addWidget(widget)
    layout.addLayout(row)
    return row
