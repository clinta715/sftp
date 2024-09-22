import sys
import base64
import os
import argparse
import json
import platform
import time
# import qdarktheme
import logging

from icecream import ic
ic.configureOutput(prefix='DEBUG | ')
ic.disable()
from PyQt5.QtWidgets import QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QCompleter, QComboBox, QSpinBox, QTabWidget, QMessageBox
from PyQt5.QtCore import pyqtSignal, QObject, QCoreApplication, Qt, QTimer, QEvent
from cryptography.fernet import Fernet

# Configure logging
##logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
##logging.getLogger("paramiko").setLevel(logging.WARNING)

from sftp_downloadworkerclass import transferSignals, add_sftp_job, clear_sftp_queue
from PyQt5.QtCore import pyqtSignal
from sftp_backgroundthreadwindow import BackgroundThreadWindow
# from sftp_editwindowclass import EditDialogContainer
from sftp_hostdataeditor import HostDataEditor, save_connection_data, load_connection_data
from sftp_remotefilebrowserclass import RemoteFileBrowser
from sftp_filebrowserclass import FileBrowser
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QMenu
from sftp_creds import get_credentials, set_credentials, del_credentials, create_random_integer
import os
import subprocess
import platform

MAX_HOST_DATA_SIZE = 10  # Set your desired maximum size

class CustomComboBox(QComboBox):
    editingFinished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()

# Define SIZE_UNIT and WorkerSignals as necessary
MAX_TRANSFERS = 4

class WorkerSignals(QObject):
    error = pyqtSignal(int, str)

class MainWindow(QMainWindow):  # Inherits from QMainWindow
    def __init__(self):
        super().__init__()
        self.transfers_message = transferSignals()

        # Custom data structure to store hostname, username, and password together
        self.create_initial_data()
        self.host_data = {
            "hostnames" : {},
            "usernames" : {},
            "passwords" : {},
            "ports" : {} }

        # Previous text to check for changes
        QCoreApplication.instance().aboutToQuit.connect(self.cleanup)
        self.hostnames = []
        self.sessions = []
        self.observers = []
        self._notifying = False  # Flag to track notification status
        self.output_console = QTextEdit()
        self.output_console.setReadOnly(True)

        # Create and connect to the error signal from WorkerSignals
        self.worker_signals = WorkerSignals()
        self.worker_signals.error.connect(self._display_error)

        # Load saved connection data and encryption key
        self.host_data = load_connection_data()

        # Initialize UI after loading connection data
        self.init_ui()

        # Create the background thread window
        self.backgroundThreadWindow = BackgroundThreadWindow()
        self.backgroundThreadWindow.setWindowTitle("Transfer Queue")
        self.backgroundThreadWindow.show()

        # Install event filter for window movement
        self.installEventFilter(self)

    def _display_error(self, transfer_id, message):
        # Display error in a message box
        QMessageBox.critical(self, "Error", f"Transfer {transfer_id}: {message}")
        
        # Display the error in the global output console
        self.global_output_console.append(f"Error in transfer {transfer_id}: {message}")
        
        # Display the error in the tab-specific console if it exists
        current_tab = self.tab_widget.currentWidget()
        if hasattr(current_tab, 'output_console'):
            current_tab.output_console.append(f"Error in transfer {transfer_id}: {message}")

    def init_ui(self):
        # Initialize input widgets
        self.container_layout = QVBoxLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.port_selector = QLineEdit()

        # Initialize buttons
        self.connect_button = QPushButton("Connect")
        self.edit_button = QPushButton("Edit Host Data")
        self.transfers_button = QPushButton("Show/Hide Transfers")
        self.clear_queue_button = QPushButton("Clear Queue")
        self.transfers = {}  # Dictionary to store active transfers

        # Initialize hostname combo box
        self.hostname_combo = CustomComboBox(self)  # Pass self as parent
        self.hostname_combo.setEditable(True)
        self.populate_hostname_combo()  # New method to populate the combo box

        # Initialize spin box
        self.spinBox = QSpinBox()
        self.spinBox.setMinimum(2)
        self.spinBox.setMaximum(10)
        self.spinBox.setValue(4)
        self.spinBox.valueChanged.connect(self.on_value_changed)  # Ensure this slot is implemented

        # Initialize layouts
        self.init_top_bar_layout()
        self.init_button_layout()

        # Set main layout
        self.top_layout = QVBoxLayout()
        self.top_layout.addLayout(self.top_bar_layout)
        self.top_layout.addLayout(self.button_layout)

        # Set up central widget
        self.central_widget = QWidget()
        self.central_widget.setLayout(self.top_layout)
        self.setCentralWidget(self.central_widget)

        # Initialize tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.closeTab)

        # Additional setup if necessary
        self.setup_hostname_completer()

        # Add the tab widget to the top layout
        # Create global output console
        self.global_output_console = QTextEdit()
        self.global_output_console.setReadOnly(True)
        self.global_output_console.setMaximumHeight(100)  # Reduced height from 150 to 100
        
        # Add the global output console to the layout
        self.top_layout.addWidget(self.global_output_console)
        
        # Add the tab widget below the global output console
        self.top_layout.addWidget(self.tab_widget)

    def init_top_bar_layout(self):
        self.top_bar_layout = QHBoxLayout()
        self.top_bar_layout.addWidget(self.hostname_combo, 3)
        self.top_bar_layout.addWidget(self.username, 3)
        self.top_bar_layout.addWidget(self.password, 3)
        self.top_bar_layout.addWidget(self.port_selector, 1)
        self.top_bar_layout.addWidget(self.spinBox)

        # Assuming self.connect_button_pressed is a method that handles the connection logic
        # Connect returnPressed signal of QLineEdit widgets to connect_button_pressed
        self.username.returnPressed.connect(self.connect_button_pressed)
        self.password.returnPressed.connect(self.connect_button_pressed)
        self.port_selector.returnPressed.connect(self.connect_button_pressed)

    def init_button_layout(self):
        self.button_layout = QHBoxLayout()
        self.button_layout.addWidget(self.connect_button)
        self.button_layout.addWidget(self.transfers_button)
        self.button_layout.addWidget(self.clear_queue_button)
        self.button_layout.addWidget(self.edit_button)

        # Connect the clicked signal of the edit button to the open_edit_dialog method
        self.edit_button.clicked.connect(self.open_edit_dialog)

        # Connect the clicked signal of the connect button to the connect_button_pressed method
        self.connect_button.clicked.connect(self.connect_button_pressed)
        self.clear_queue_button.clicked.connect(clear_sftp_queue)

    def setup_hostname_completer(self):
        # Make sure self.hostnames is initialized and filled with data
        self.hostname_completer = QCompleter(self.hostnames)
        self.hostname_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.hostname_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.hostname_combo.setCompleter(self.hostname_completer)

        # Connect signals for hostname combo box
        self.hostname_combo.currentIndexChanged.connect(self.hostname_changed)  # Ensure this slot is implemented
        self.hostname_combo.activated.connect(self.hostname_changed)
        self.hostname_combo.editingFinished.connect(self.hostname_changed)        

    def populate_hostname_combo(self):
        # Clear existing items
        self.hostname_combo.clear()
        
        # Add hostnames from the host_data
        for hostname in self.host_data['hostnames'].keys():
            self.hostname_combo.addItem(hostname)
        
        # Update the hostnames list for the completer
        self.hostnames = list(self.host_data['hostnames'].keys())

    def prepare_container_widget(self):
        # Create a container widget
        container_widget = QWidget()

        # Create the browsers
        self.left_browser = FileBrowser("Local Files", self.session_id)
        self.right_browser = RemoteFileBrowser("Remote Files", self.session_id)

        # Create a layout for the browsers
        browser_layout = QHBoxLayout()
        
        browser_layout.addWidget(self.left_browser)
        browser_layout.addWidget(self.right_browser)

        self.left_browser.add_observer(self.right_browser)
        self.right_browser.add_observer(self.left_browser)
        self.backgroundThreadWindow.add_observee(self.right_browser)
        self.backgroundThreadWindow.add_observee(self.left_browser)

        # Create tab-specific output console
        tab_output_console = QTextEdit()
        tab_output_console.setReadOnly(True)
        tab_output_console.setMaximumHeight(100)  # Limit the height

        # Create the main layout
        main_layout = QVBoxLayout()
        main_layout.addLayout(browser_layout)
        main_layout.addWidget(tab_output_console)
        
        # Store the tab-specific console in the container widget
        container_widget.output_console = tab_output_console

        # Set the main layout to the container widget
        container_widget.setLayout(main_layout)
        self.log_connection_success()

        # Initialize the remote browser model
        self.right_browser.initialize_model()
            
        return container_widget

    def closeTab(self, index):
        # Close the tab at the given index
        widget_to_remove = self.tab_widget.widget(index)
        self.tab_widget.removeTab(index)

        # Close SFTP connection
        if hasattr(widget_to_remove, 'right_browser'):
            widget_to_remove.right_browser.close_sftp_connection()

        # Delete the widget if necessary
        widget_to_remove.deleteLater()
        self.backgroundThreadWindow.remove_observee(widget_to_remove.left_browser)
        self.backgroundThreadWindow.remove_observee(widget_to_remove.right_browser)

    def setup_left_browser(self, session_id):
        self.session_id = session_id
        # creds = get_credentials(self.session_id)
        set_credentials(self.session_id, 'current_local_directory', os.getcwd())

        try:
            self.left_browser = FileBrowser("Local Files", self.session_id)
            self.left_browser.table.setFocusPolicy(Qt.StrongFocus)
            self.left_browser.message_signal.connect(self.update_console)
            self.container_layout.addWidget(self.left_browser)

        except Exception as e:
            print(f"Error setting up left browser: {e}")
            pass

    def setup_right_browser(self, session_id):
        self.session_id = session_id
        try:
            self.right_browser = RemoteFileBrowser(title=self.title, session_id=self.session_id)
            self.right_browser.table.setFocusPolicy(Qt.StrongFocus)
            self.right_browser.message_signal.connect(self.update_console)

        except Exception as e:
            pass

    def YouAddTab(self, session_id, widget):
        self.session_id = session_id

        # Assuming these methods are correctly defined and handle their tasks appropriately
        self.title = self.get_session_title(self.session_id)
        
        # print("call setup_left_browser")
        self.setup_left_browser(self.session_id)
        self.setup_right_browser(self.session_id)
        # Create tab-specific output console
        tab_output_console = QTextEdit()
        tab_output_console.setReadOnly(True)
        tab_output_console.setMaximumHeight(100)  # Limit the height

        # Prepare the container widget
        container_widget = self.prepare_container_widget()

        # Add widget to the tab widget with the title
        # Add the container widget as a new tab
        tab_title = self.get_session_title(session_id)  # Retrieves the title for the tab
        self.tab_widget.addTab(container_widget, tab_title)

        self.log_connection_success()  # Ensure this method is implemented

    def create_cancel_button(self, transfer_id):
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(lambda: self.cancel_transfer(transfer_id))
        return cancel_button

    def cancel_transfer(self, transfer_id):
        if transfer_id in self.transfers:
            self.transfers[transfer_id].download_worker._stop_flag = True
            self.message_signal.emit(f"Cancelling transfer {transfer_id}")

    def initialize_session_credentials(self, session_id):
        self.session_id = session_id

        self.title = self.get_session_title(self.session_id)
        self.tab_widget.addTab(self.tab_widget, self.title)
        self.sessions.append(self.tab_widget)

    def get_session_title(self, session_id):
        self.session_id = session_id
        creds = get_credentials(self.session_id)

        try:
            title = creds.get('hostname') if creds else "Unknown Hostname"
        except KeyError:
            title = "Unknown Hostname"
        return title

    def setup_output_console(self):
        # Initialize output console
        self.output_console = QTextEdit()
        self.output_console.setReadOnly(True)
        self.container_layout.addWidget(self.output_console)

    def log_connection_success(self):
        success_message = "Connected successfully"
        self.output_console.append(success_message)

    def hostname_changed(self):
        self.current_hostname = self.hostname_combo.currentText().strip()  # Strip whitespace

        # Access data from the nested dictionaries
        if self.current_hostname in self.host_data['hostnames']:
            username = self.host_data['usernames'].get(self.current_hostname, '')
            password = self.host_data['passwords'].get(self.current_hostname, '')
            port = self.host_data['ports'].get(self.current_hostname, '')

            self.username.setText(username)
            self.password.setText(password)
            self.port_selector.setText(str(port))  # Convert port to string
        else:
            # If the hostname is not in the history, clear the fields
            self.username.clear()
            self.password.clear()
            self.port_selector.clear()

        # Update the UI
        self.username.repaint()
        self.password.repaint()
        self.port_selector.repaint()

    def removeTab(self, session_id):
        creds = get_credentials(self.session_id)
        self.tabWidget.removeTab( self.tabs[session_id] )
        del self.tabs[session_id]  # Remove the reference from the list
        del_credentials(self.session_id)

    def on_value_changed(self, value):
        global MAX_TRANSFERS
        MAX_TRANSFERS = value
        
    def update_console(self, message):
        # Update the console with the received message
        self.output_console.append(message)

    def update_completer(self):
        # Update the list of hostnames
        self.hostnames = list(self.host_data['hostnames'].keys())  # Adjusted to fetch keys from the 'hostnames' dict within host_data

        # Clear and repopulate the hostname combo box
        self.hostname_combo.clear()
        self.hostname_combo.addItems(self.hostnames)

        # Reinitialize the completer with the updated list
        self.hostname_completer = QCompleter(self.hostnames)
        self.hostname_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.hostname_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.hostname_combo.setCompleter(self.hostname_completer)

    def open_edit_dialog(self):
        # Create an instance of HostDataEditor as a QDialog
        editor = HostDataEditor()  # Pass self if you need to reference the main window

        # Set dialog properties (optional)
        editor.setWindowTitle("Edit Host Data")
        editor.setModal(True)  # Make it modal, if desired

        # Show the dialog
        editor.exec_()  # Use exec_() for modal dialogs

    def onHostDataChanged(self, updated_data):
        self.host_data = updated_data
        save_connection_data()
        self.update_completer()

    def onEntryDoubleClicked(self, entry):
        hostname = entry.get("hostname", "localhost")
        username = entry.get("username", "guest")
        password = entry.get("password", "guest")
        port = entry.get("port", "22")

        self.connect(hostname=hostname, username=username, password=password, port=port)

    def closeEvent(self, event):
        # Assuming you have a reference to BackgroundThreadWindow instance
        if self.backgroundThreadWindow:
            self.backgroundThreadWindow.close()
        event.accept()  # Accept the close event

    # Function to safely clear a queue
    def clear_queue(self, q):
        try:
            while True:  # Continue until an Empty exception is raised
                q.get_nowait()  # Remove an item from the queue
                q.task_done()  # Indicate that a formerly enqueued task is complete
        except Exception as e:
            pass  # Queue is empty, break the loop

    def connect_button_pressed(self):
        try:
            session_id = self.connect()
            if session_id is None:
                # Connection failed, error has already been displayed
                return
            # If needed, add any post-connection logic here
        except Exception as e:
            error_message = f"Connection failed: {str(e)}"
            self.display_error(error_message)
            self.update_console(error_message)

    def display_error(self, transfer_id, message):
        # Display error in a message box
        QMessageBox.critical(self, "Error", f"Transfer {transfer_id}: {message}")
        
        # Display the error in the global output console
        self.global_output_console.append(f"Error in transfer {transfer_id}: {message}")
        
        # Display the error in the tab-specific console if it exists
        current_tab = self.tab_widget.currentWidget()
        if hasattr(current_tab, 'output_console'):
            current_tab.output_console.append(f"Error in transfer {transfer_id}: {message}")

    def connect(self, hostname="localhost", username="guest", password="guest", port="22"):
        self.temp_hostname = self.hostname_combo.currentText() if hostname == "localhost" and self.hostname_combo.currentText() else hostname
        
        # Print to the global output console
        self.global_output_console.append(f"Attempting to connect to {self.temp_hostname}...")
        QApplication.processEvents()  # Force GUI update
        
        try:
            self.session_id = create_random_integer()
            self.global_output_console.append(f"Created session ID: {self.session_id}")
            QApplication.processEvents()

            # Hostname, username, password, and port handling
            self.temp_hostname = self.hostname_combo.currentText() if hostname == "localhost" and self.hostname_combo.currentText() else hostname
            self.temp_username = self.username.text() if username == "guest" and self.username.text() else username
            self.temp_password = self.password.text() if password == "guest" and self.password.text() else password
            self.temp_port = self.port_selector.text() or port or "22"

            self.global_output_console.append(f"Using hostname: {self.temp_hostname}, username: {self.temp_username}, port: {self.temp_port}")
            QApplication.processEvents()

            if not self.temp_hostname:
                raise ValueError("Hostname is required")
            if not self.temp_username:
                raise ValueError("Username is required")
            if not self.temp_password:
                raise ValueError("Password is required")
            try:
                self.temp_port = int(self.temp_port)  # Validate port is a number
            except ValueError:
                raise ValueError("Port must be a valid number")

            # Set credentials synchronously
            self.global_output_console.append("Setting credentials...")
            QApplication.processEvents()
            self.set_credentials_async()

            # Test the connection
            self.global_output_console.append("Testing connection...")
            QApplication.processEvents()
            self.test_connection()

            # Create a new QWidget as a container for both the file table and the output console
            self.global_output_console.append("Preparing container widget...")
            QApplication.processEvents()
            self.container_widget = self.prepare_container_widget()

            # Add tab synchronously
            self.global_output_console.append("Adding new tab...")
            QApplication.processEvents()
            self.YouAddTab(self.session_id, self.container_widget)

            self.global_output_console.append(f"Successfully connected to {self.temp_hostname}")
            QApplication.processEvents()

            # Save connection data synchronously
            self.global_output_console.append("Saving connection data...")
            QApplication.processEvents()
            self.save_connection_data_async()

            return self.session_id
        except ValueError as ve:
            error_message = str(ve)
            QMessageBox.critical(self, "Connection Error", error_message)
            self.global_output_console.append(f"Connection failed: {error_message}")
            QApplication.processEvents()
        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            QMessageBox.critical(self, "Connection Error", error_message)
            self.global_output_console.append(f"Connection failed: {error_message}")
            QApplication.processEvents()
        return None

    def test_connection(self):
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.global_output_console.append(f"Attempting SSH connection to {self.temp_hostname}:{self.temp_port}...")
            QApplication.processEvents()
            ssh.connect(self.temp_hostname, port=self.temp_port, username=self.temp_username, password=self.temp_password)
            self.global_output_console.append("SSH connection successful")
            QApplication.processEvents()
            ssh.close()
        except Exception as e:
            self.global_output_console.append(f"SSH connection failed: {str(e)}")
            QApplication.processEvents()
            raise Exception(f"Failed to connect: {str(e)}")

    def set_credentials_async(self):
        set_credentials(self.session_id, 'hostname', self.temp_hostname)
        set_credentials(self.session_id, 'username', self.temp_username)
        set_credentials(self.session_id, 'password', self.temp_password)
        set_credentials(self.session_id, 'port', str(self.temp_port))
        set_credentials(self.session_id, 'current_local_directory', os.getcwd())
        set_credentials(self.session_id, 'current_remote_directory', '.')

    def save_connection_data_async(self):
        self.host_data["hostnames"][self.temp_hostname] = self.temp_hostname
        self.host_data["usernames"][self.temp_hostname] = self.temp_username
        self.host_data["passwords"][self.temp_hostname] = self.temp_password
        self.host_data["ports"][self.temp_hostname] = str(self.temp_port)
        save_connection_data(self.host_data)
        self.update_completer()

    def create_initial_data(self):
        """
        Create initial data for the application.
        This includes defining the data to be written to the JSON file.
        """
        # Example data for demonstration purposes
        self.host_data = {
            "localhost": {
                "username": "guest",
                "password": "WjNWbGMzUT0=",  # Note: This should be securely stored/encrypted
                "port": 22  # Port should be an integer
            }
        }
            
    def cleanup(self):
        print("Cleanup method called")
        cleanup_tasks = [
            self.close_sftp_connections,
            clear_sftp_queue,
            self.stop_background_thread,
            lambda: save_connection_data(self.host_data)
        ]
        for task in cleanup_tasks:
            try:
                print(f"Performing cleanup task: {task.__name__ if hasattr(task, '__name__') else 'lambda'}")
                task()
            except Exception as e:
                print(f"Error during cleanup task: {str(e)}")
        print("All cleanup tasks completed.")
        QTimer.singleShot(0, QCoreApplication.instance().quit)

    # Remove the perform_next_cleanup_task method as it's no longer needed

    def close_sftp_connections(self):
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if hasattr(widget, 'right_browser'):
                widget.right_browser.close_sftp_connection()

    def stop_background_thread(self):
        if hasattr(self, 'backgroundThreadWindow'):
            self.backgroundThreadWindow.close()
        add_sftp_job(".", False, ".", False, "localhost", "guest", "guest", 69, "end", 69)
        # Wait for the background thread to finish
        for _ in range(10):  # Wait for up to 1 second
            QApplication.processEvents()
            time.sleep(0.1)
            if not self.backgroundThreadWindow.isVisible():
                break

    def closeEvent(self, event):
        if self.backgroundThreadWindow.active_transfers > 0:
            reply = QMessageBox.question(
                self, 'Confirm Exit',
                'There are active file transfers. Are you sure you want to exit?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
        event.accept()
        self.cleanup()  # Run cleanup after accepting the event

    def position_background_window(self):
        main_geo = self.geometry()
        background_geo = self.backgroundThreadWindow.geometry()
        
        # Position the background window to the right of the main window
        new_x = main_geo.x() + main_geo.width() + 10  # 10 pixels gap
        new_y = main_geo.y()
        
        self.backgroundThreadWindow.setGeometry(new_x, new_y, background_geo.width(), background_geo.height())

    def eventFilter(self, source, event):
        if source == self and event.type() == QEvent.Move:
            self.position_background_window()
        return super().eventFilter(source, event)

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="FTP/SFTP Client")
    parser.add_argument("-H", "--hostname", help="Initial hostname to connect to")
    parser.add_argument("-u", "--username", help="Username for the connection")
    parser.add_argument("-p", "--password", help="Password for the connection")
    parser.add_argument("-P", "--port", type=int, default=22, help="Port for the connection (default: 22)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    # if args.debug:
    # ic.enable()
    # else:
    ic.disable()

    def hide_transfers_window():
        if not hasattr(hide_transfers_window, "transfers_hidden"):
            hide_transfers_window.transfers_hidden = 1  # Initialize it once
            main_window.backgroundThreadWindow.hide()
        elif hide_transfers_window.transfers_hidden == 0:
            main_window.backgroundThreadWindow.hide()
            hide_transfers_window.transfers_hidden = 1
        elif hide_transfers_window.transfers_hidden == 1:
            main_window.backgroundThreadWindow.show()
            main_window.position_background_window()  # Reposition when showing
            hide_transfers_window.transfers_hidden = 0

    app = QApplication(sys.argv)
    # app.setStyle('Fusion')
    # qdarktheme.setup_theme()

    # create the main window of the application
    main_window = MainWindow()
    main_window.setWindowTitle("FTP/SFTP Client")
    main_window.resize(800, 600)
    main_window.show()
    main_window.transfers_message.showhide.connect(hide_transfers_window)

    # Position the background window
    main_window.position_background_window()

    # If command line arguments are provided, initiate the connection
    if args.hostname:
        try:
            main_window.connect(
                hostname=args.hostname,
                username=args.username or "guest",
                password=args.password or "guest",
                port=str(args.port)
            )
        except Exception as e:
            print(f"Error connecting: {str(e)}")

    # Connect the aboutToQuit signal directly to the cleanup method
    app.aboutToQuit.connect(main_window.cleanup)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
