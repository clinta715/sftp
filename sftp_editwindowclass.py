from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QPushButton, QMenu, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy, QDialog, QStyledItemDelegate
from PyQt5.QtCore import pyqtSignal, Qt

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

    def __init__(self, host_data, parent=None):
        super().__init__(parent)
        self.host_data = host_data
        self.initUI()
        self.table.cellDoubleClicked.connect(self.onCellDoubleClicked)

    def initUI(self):
        self.table = CustomTableWidget(self, len(self.host_data), 4)  # Use the custom table widget
        # Assuming self.table is your QTableWidget or QTableView
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setHorizontalHeaderLabels(["Hostname", "Username", "Password", "Port"])

        try:
            self.load_data_from_file("sftp.json")
        except:
            ic("can't load sftp.json")
            self.host_data = {
                'localhost': {
                    'username': 'guest',
                    'password': base64.b64encode('guest'.encode()).decode(),
                    'port': 22
                }
            }
            # Save the initial data to the file
            self.save_data()         

        # Stretch the last section to fill the space
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

        save_button = QPushButton("Save")
        connect_button = QPushButton("Connect")
        save_button.clicked.connect(self.save_data_to_file)
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
        for row, (hostname, details) in enumerate(self.host_data.items()):
            # Create table items for hostname, username, and port
            hostname_item = QTableWidgetItem(hostname)
            username_item = QTableWidgetItem(details['username'])
            port_item = QTableWidgetItem(str(details['port']))

            # Set the items as editable
            hostname_item.setFlags(hostname_item.flags() | Qt.ItemIsEditable)
            username_item.setFlags(username_item.flags() | Qt.ItemIsEditable)
            port_item.setFlags(port_item.flags() | Qt.ItemIsEditable)

            # Add the items to the table
            self.table.setItem(row, 0, hostname_item)
            self.table.setItem(row, 1, username_item)
            self.table.setItem(row, 3, port_item)

            # Use PasswordItem for the password, ensure it's editable if it's a custom class
            password_item = PasswordItem(details['password'])
            # Uncomment and modify the following line if PasswordItem needs to be explicitly set as editable
            # password_item.setFlags(password_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, 2, password_item)

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
        try:
            with open(filename, "r") as file:
                data_loaded = json.load(file)

            # Decode the Base64-encoded passwords
            self.host_data = {}
            for hostname, details in data_loaded.items():
                decoded_password = base64.b64decode(details['password']).decode()
                self.host_data[hostname] = {
                    'username': details['username'],
                    'password': decoded_password,
                    'port': details['port']
                }

        except:
            # revised the logic here so basiacally any error on reading the sftp.json file results in resetting it to example data
            # executive decision was made that to do so was outside the scope of a 'quick and dirty' sftp application and would begin to approach 'time consuming and elegant'
            # Create initial data
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
        # Takes data out of the table and puts it in self.host_data while removing duplicates
        new_host_data = {}
        seen_hostnames = set()

        for row in range(self.table.rowCount()):
            if self.table.item(row, 0) == None:
                continue
            if self.table.item(row, 1) == None:
                continue
            if self.table.item(row, 2) == None:
                continue
            if self.table.item(row, 3) == None:
                continue
            # Repeat similar checks for other columns.

            hostname = self.table.item(row, 0).text()
            username = self.table.item(row, 1).text()
            password = self.table.item(row, 2).text()
            port = self.table.item(row, 3).text()

            # Base64 encode the password
            encoded_password = base64.b64encode(password.encode()).decode()

            # Check if the hostname is already seen, and skip duplicates
            if hostname not in seen_hostnames:
                new_host_data[hostname] = {
                    'username': username,
                    'password': encoded_password,
                    'port': port
                }

                seen_hostnames.add(hostname)

        self.host_data = new_host_data
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
