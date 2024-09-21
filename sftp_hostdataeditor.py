import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout,
    QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView
)
from PyQt5.QtCore import Qt
import json
from cryptography.fernet import Fernet
from PyQt5.QtWidgets import QDialog  # Make sure to import QDialog
from icecream import ic

encryption_key = []
cipher_suite = []

def save_connection_data(host_data):
    global encryption_key, cipher_suite
    data = {
        "hostnames": host_data["hostnames"],
        "usernames": host_data["usernames"],
        "passwords": {k: cipher_suite.encrypt(v.encode()).decode() for k, v in host_data["passwords"].items()},
        "ports": host_data["ports"],
        "encryption_key": encryption_key  # No need to decode the encryption key
    }
    with open('connection_data.json', 'w') as f:
        json.dump(data, f)

def load_connection_data():
    global encryption_key, cipher_suite
    host_data = {"hostnames": {}, "usernames": {}, "passwords": {}, "ports": {}}

    try:
        with open('connection_data.json', 'r') as f:
            data = json.load(f)

        encryption_key = data.get("encryption_key", Fernet.generate_key())
        cipher_suite = Fernet(encryption_key)

        host_data["hostnames"] = data.get("hostnames", {})
        host_data["usernames"] = data.get("usernames", {})
        host_data["passwords"] = {k: cipher_suite.decrypt(v.encode()).decode() for k, v in data.get("passwords", {}).items()}
        host_data["ports"] = data.get("ports", {})

        return host_data
    except Exception as e:
        ic(e)
        data = {
            "hostnames": {
                "example.com": "example.com",
                "testserver.local": "testserver.local"
            },
            "usernames": {
                "example.com": "user1",
                "testserver.local": "user2"
            },
            "passwords": {
                "example.com": "password123",
                "testserver.local": "testpass"
            },
            "ports": {
                "example.com": 22,
                "testserver.local": 2222
            }
        }
        ic(data)
        
        # Set host_data with either loaded or fake data
        host_data = data
        return data

class HostDataEditor(QDialog):  # Change QWidget to QDialog
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Host Data Editor")
        self.resize(800, 600)  # Set an initial window size

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Hostname", "Username", "Password", "Port"])
        
        # Set the horizontal header to resize based on content
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)  # Ensure last section takes up remaining space

        # You can also set the vertical header to resize based on content if needed
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        self.add_button = QPushButton("Add Row")
        self.add_button.clicked.connect(self.add_row)

        self.delete_button = QPushButton("Delete Selected Row")
        self.delete_button.clicked.connect(self.delete_row)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_data)

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        layout.addWidget(self.add_button)
        layout.addWidget(self.delete_button)
        layout.addWidget(self.save_button)
        self.setLayout(layout)

        # Initialize host_data before loading data
        self.host_data = {"hostnames": {}, "usernames": {}, "passwords": {}, "ports": {}}
        
        # Load the data
        self.host_data = self.load_data()
        self.update_table()

    def load_data(self):
        try:
            data = load_connection_data()
            ic(data)
            self.update_table()
            return data
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load data: {str(e)}")

    def add_row(self):
        row_count = self.table.rowCount()
        self.table.insertRow(row_count)

    def delete_row(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            hostname_item = self.table.item(selected_row, 0)
            if hostname_item:
                hostname = hostname_item.text()
                # Remove the corresponding data from host_data
                self.host_data["hostnames"].pop(hostname, None)
                self.host_data["usernames"].pop(hostname, None)
                self.host_data["passwords"].pop(hostname, None)
                self.host_data["ports"].pop(hostname, None)
            self.table.removeRow(selected_row)
        else:
            QMessageBox.warning(self, "No selection", "Please select a row to delete.")

    def save_data(self):
        try:
            # Collect data from the table before saving
            for i in range(self.table.rowCount()):
                hostname_item = self.table.item(i, 0)
                username_item = self.table.item(i, 1)
                password_item = self.table.item(i, 2)
                port_item = self.table.item(i, 3)

                if not all([hostname_item, username_item, password_item, port_item]):
                    raise ValueError("All fields must be filled out.")

                hostname = hostname_item.text()
                username = username_item.text()
                password = password_item.text()
                port = int(port_item.text())

                # Update host_data dictionary
                self.host_data["hostnames"][hostname] = hostname
                self.host_data["usernames"][hostname] = username
                self.host_data["passwords"][hostname] = password  # Will be encrypted on save
                self.host_data["ports"][hostname] = port

            # Save the data using the parent's save function
            save_connection_data(self.host_data)
            QMessageBox.information(self, "Success", "Data saved successfully.")
        except ValueError as e:
            QMessageBox.critical(self, "Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Unknown Error", f"An error occurred: {str(e)}")

    def update_table(self):
        self.table.setRowCount(len(self.host_data["hostnames"]))
        for i, hostname in enumerate(self.host_data["hostnames"]):
            self.table.setItem(i, 0, QTableWidgetItem(hostname))
            self.table.setItem(i, 1, QTableWidgetItem(self.host_data["usernames"][hostname]))
            self.table.setItem(i, 2, QTableWidgetItem(self.host_data["passwords"][hostname]))  # Decrypted password
            self.table.setItem(i, 3, QTableWidgetItem(str(self.host_data["ports"][hostname])))

    def closeEvent(self, event):
        # Save data when the window is closed
        try:
            self.save_data()  # Call save_data() to collect and save the data
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save data on close: {str(e)}")
        event.accept()  # Accept the close event
