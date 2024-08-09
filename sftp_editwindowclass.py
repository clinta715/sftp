from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QPushButton, QMenu, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy, QDialog, QStyledItemDelegate
from PyQt5.QtCore import pyqtSignal, Qt
import base64

class PasswordDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setEchoMode(QLineEdit.Password)
        return editor

    def displayText(self, value, locale):
        return '*' * len(str(value))

class PasswordItem(QTableWidgetItem):
    def __init__(self, text):
        super().__init__(text)
        self.setFlags(self.flags() | Qt.ItemIsEditable)

class CustomTableWidget(QTableWidget):
    def __init__(self, parent=None, row_count=0, column_count=0):
        super().__init__(row_count, column_count, parent)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item is not None:
            row = item.row()

            contextMenu = QMenu(self)
            connectAction = contextMenu.addAction("Connect")
            addAction = contextMenu.addAction("Add")
            removeAction = contextMenu.addAction("Remove")

            action = contextMenu.exec_(self.mapToGlobal(event.pos()))

            if action == connectAction:
                # Call a method of the parent, make sure it exists
                self.parent().onCellDoubleClicked(row, 1)
            if action == addAction:
                self.parent().add_row()
            if action == removeAction:
                self.parent().remove_row()

class EditDialog(QDialog):
    entryDoubleClicked = pyqtSignal(dict)

    dataChanged = pyqtSignal(dict)

    def __init__(self, host_data, parent=None):
        super().__init__(parent)
        self.host_data = host_data
        self.initUI()
        self.table.cellDoubleClicked.connect(self.onCellDoubleClicked)

    def initUI(self):
        self.table = CustomTableWidget(self, 0, 4)  # Start with 0 rows, we'll add them as we load data
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setHorizontalHeaderLabels(["Hostname", "Username", "Password", "Port"])

        # Stretch the last section to fill the space
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

        save_button = QPushButton("Save")
        connect_button = QPushButton("Connect")
        save_button.clicked.connect(self.save_data)
        connect_button.clicked.connect(self.connect_button_clicked)
        layout = QVBoxLayout()
        layout.addWidget(self.table)
        layout.addWidget(save_button)
        layout.addWidget(connect_button)
        self.setLayout(layout)
        self.load_data()
        # Hide row numbers
        self.table.verticalHeader().setVisible(False)
        # Set the password delegate
        password_delegate = PasswordDelegate()
        self.table.setItemDelegateForColumn(2, password_delegate)  # Password column

    def connect_button_clicked(self):
        selected_items = self.table.selectedItems()

        if selected_items:
            first_selected_item = selected_items[0]
            row = first_selected_item.row()
        else:
            return

        self.onCellDoubleClicked(row, 1)

    def onCellDoubleClicked(self, row, column):
        # Assuming the order of columns is hostname, username, password, port
        try:
            temp_hostname = self.table.item(row, 0).text()
        except:
            temp_hostname = "localhost"
        try:
            temp_username = self.table.item(row, 1).text()
        except:
            temp_username = "guest"
        try:
            temp_password = self.table.item(row, 2).text()
        except:
            temp_password = "guest"
        try:
            temp_port = self.table.item(row, 3).text()
        except:
            temp_port = "22"

        entry = {"hostname": temp_hostname, "username": temp_username, "password": temp_password, "port": temp_port}
        self.entryDoubleClicked.emit(entry)

    def load_data(self):
        self.table.setRowCount(0)  # Clear existing rows
        for hostname, details in self.host_data['hostnames'].items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            # Create table items for hostname, username, password, and port
            hostname_item = QTableWidgetItem(hostname)
            username_item = QTableWidgetItem(self.host_data['usernames'].get(hostname, ''))
            password_item = PasswordItem(self.host_data['passwords'].get(hostname, ''))
            port_item = QTableWidgetItem(str(self.host_data['ports'].get(hostname, '')))

            # Set the items as editable
            for item in [hostname_item, username_item, password_item, port_item]:
                item.setFlags(item.flags() | Qt.ItemIsEditable)

            # Add the items to the table
            self.table.setItem(row, 0, hostname_item)
            self.table.setItem(row, 1, username_item)
            self.table.setItem(row, 2, password_item)
            self.table.setItem(row, 3, port_item)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item is not None:
            row = item.row()

        contextMenu = QMenu(self)

        addAction = contextMenu.addAction("Add")
        removeAction = contextMenu.addAction("Remove")
        connectAction = contextMenu.addAction("Connect")

        action = contextMenu.exec_(self.mapToGlobal(event.pos()))

        if action == addAction:
            self.add_row()
            self.save_data()
        elif action == removeAction:
            self.remove_row()
        elif action == connectAction:
            self.onCellDoubleClicked(row, 1)

    def add_row(self):
        row_count = self.table.rowCount()
        self.table.insertRow(row_count)
        # Initialize cells in the new row (if needed)
        for col in range(self.table.columnCount()):
            item = QTableWidgetItem("")
            self.table.setItem(row_count, col, item)

    def remove_row(self):
        row_count = self.table.rowCount()
        if row_count > 1:  # To ensure there's at least one row remaining
            self.table.removeRow(row_count - 1)

    def load_data_from_file(self, filename="sftp.json"):
        self.host_data = {
            'localhost': {
            'username': 'guest',
            'password': base64.b64encode('guest'.encode()).decode(),
            'port': 22
            }
        }
            
        # Save the initial data to the file
        self.save_data()

    def save_data(self):
        new_host_data = {
            "hostnames": {},
            "usernames": {},
            "passwords": {},
            "ports": {}
        }
        seen_hostnames = set()

        for row in range(self.table.rowCount()):
            items = [self.table.item(row, col) for col in range(4)]
            if all(items):  # Ensure all cells in the row have data
                hostname, username, password, port = [item.text() for item in items]
                
                if hostname not in seen_hostnames:
                    new_host_data["hostnames"][hostname] = hostname
                    new_host_data["usernames"][hostname] = username
                    new_host_data["passwords"][hostname] = password
                    new_host_data["ports"][hostname] = port
                    seen_hostnames.add(hostname)

        self.host_data = new_host_data
        self.dataChanged.emit(self.host_data)
        self.accept()

class EditDialogContainer(QWidget):
    def __init__(self, host_data, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)  # Allow the container to expand
        self.host_data = host_data
        self.initUI()

    def initUI(self):
        # Create an instance of EditDialog
        self.editDialog = EditDialog(self.host_data)
        # Set size policy if needed
        self.editDialog.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Ensure EditDialog is a QWidget or contains QWidget(s)
        if not isinstance(self.editDialog, QWidget):
            raise TypeError("EditDialog must be a QWidget or contain QWidget(s)")

        # Layout to hold the dialog
        layout = QVBoxLayout()
        layout.addWidget(self.editDialog)
        # Set size policy if needed
        self.editDialog.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.setLayout(layout)
