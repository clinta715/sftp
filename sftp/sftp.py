import sys
import base64
import os
from PyQt5.QtWidgets import QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QCompleter, QComboBox, QSpinBox,QTabWidget
from PyQt5.QtCore import pyqtSignal, QObject, QCoreApplication, Qt

from sftp_downloadworkerclass import BackgroundThreadWindow
from sftp_remotefilebrowserclass import RemoteFileBrowser

from sftp_downloadworkerclass import sftp_queue
 
MAX_HOST_DATA_SIZE = 10  # Set your desired maximum size

class SFTPJob:
    def __init__(self, source_path, is_source_remote, destination_path, is_destination_remote, hostname, username, password, port, command, id ):
        self.source_path = source_path
        self.is_source_remote = is_source_remote
        self.destination_path = destination_path
        self.is_destination_remote = is_destination_remote
        self.hostname = hostname
        self.username = username
        self.password = password
        self.port = port
        self.command = command
        self.id = id

    def to_dict(self):
        return {
            "source_path": self.source_path,
            "is_source_remote": self.is_source_remote,
            "destination_path": self.destination_path,
            "is_destination_remote": self.is_destination_remote,
            "hostname": self.hostname,
            "username": self.username,
            "password": base64.b64encode(self.password.encode()).decode(),  # Encode password
            "port": self.port,
            "command": self.command,
            "id": self.id
        }

    @staticmethod
    def from_dict(data):
        data["password"] = base64.b64decode(data["password"]).decode()  # Decode password
        return SFTPJob(**data)

response_queues = {}
sftp_current_creds = {}

class CustomComboBox(QComboBox):
    editingFinished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()

def create_random_integer():
    """
    Generates a really random positive integer using os.urandom.
    Ensures that the number is not interpreted as negative. Keeps track of generated numbers to ensure uniqueness.
    """
    # Initialize the set of generated numbers as a function attribute if it doesn't exist
    if not hasattr(create_random_integer, 'generated_numbers'):
        create_random_integer.generated_numbers = set()

    while True:
        # Generating a random byte string of length 4
        random_bytes = os.urandom(4)

        # Converting to a positive integer and masking the most significant bit
        random_integer = int.from_bytes(random_bytes, 'big') & 0x7FFFFFFF

        # Check if the number is unique
        if random_integer not in create_random_integer.generated_numbers:
            create_random_integer.generated_numbers.add(random_integer)
            return random_integer

def add_sftp_job(source_path, is_source_remote, destination_path, is_destination_remote, hostname, username, password, port, command, id ):
    job = SFTPJob(
        source_path, is_source_remote, destination_path, is_destination_remote,
        hostname, username, password, port, command, id )
    sftp_queue.put(job)

class WorkerSignals(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int)
    message = pyqtSignal(int, str)

# Define SIZE_UNIT and WorkerSignals as necessary
MAX_TRANSFERS = 4

class QueueItem:
    def __init__(self, name, id):
        self.name = name
        self.id = id

queue_display = []

class Transfer:
    def __init__(self, transfer_id, progress_bar=None, cancel_button=None, download_worker=None, active=False, hbox=None, tbox=None ):
        self.transfer_id = transfer_id
        self.progress_bar = progress_bar
        self.cancel_button = cancel_button
        self.download_worker = download_worker
        self.active = active
        self.hbox = hbox
        self.tbox = tbox

class transferSignals(QObject):
    showhide = pyqtSignal()

class MainWindow(QMainWindow):  # Inherits from QMainWindow
    def __init__(self):
        super().__init__()
        self.transfers_message = transferSignals()
        # Custom data structure to store hostname, username, and password together

        self.host_data = {
            "hostnames" : {},
            "usernames" : {},
            "passwords" : {},
            "ports" : {} }

        # Previous text to check for changes
        QCoreApplication.instance().aboutToQuit.connect(self.cleanup)
        self.hostnames = []
        self.sessions = []
        self.init_ui()

    def init_ui(self):
        # Initialize input widgets
        self.create_initial_data()
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

        # Initialize hostname combo box
        self.hostname_combo = CustomComboBox()  # Make sure CustomComboBox is defined
        self.hostname_combo.setEditable(True)

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

    def prepare_container_widget(self, use_terminal=False):
        # was in the middle of adding some code for ssh terminal windows and decided to ... not do that
        # outside the scope of a quick and dirty sftp application
        # Create a container widget
        container_widget = QWidget()

        # Create a layout for the browsers
        browser_layout = QHBoxLayout()
        
        browser_layout.addWidget(self.left_browser)
        browser_layout.addWidget(self.right_browser)

        # Create the main layout
        main_layout = QVBoxLayout()
        main_layout.addLayout(browser_layout)
        main_layout.addWidget(self.output_console)

        # Set the main layout to the container widget
        container_widget.setLayout(main_layout)
        self.log_connection_success()
            
        return container_widget

    def closeTab(self, index):
        # Close the tab at the given index
        widget_to_remove = self.tab_widget.widget(index)
        self.tab_widget.removeTab(index)

        # Delete the widget if necessary
        widget_to_remove.deleteLater()

    def YouAddTab(self, session_id, widget):
        self.session_id = session_id

        # Assuming these methods are correctly defined and handle their tasks appropriately
        self.title = self.get_session_title(self.session_id)
        
        if not self.use_terminal:
            self.setup_left_browser( self.session_id )
            self.setup_right_browser( self.session_id )
            self.setup_output_console()

        # Prepare the container widget
        container_widget = self.prepare_container_widget(self.use_terminal)

        # Add widget to the tab widget with the title
        # Add the container widget as a new tab
        tab_title = self.get_session_title(session_id)  # Retrieves the title for the tab
        self.tab_widget.addTab(container_widget, tab_title)

        self.log_connection_success()  # Ensure this method is implemented

    def initialize_session_credentials(self, session_id):
        self.session_id = session_id

        self.title = self.get_session_title(self.session_id)
        self.tab_widget.addTab(self.tab_widget, self.title)
        self.sessions.append(self.tab_widget)

    def get_session_title(self, session_id):
        self.session_id = session_id

        try:
            title = sftp_current_creds.get(self.session_id, {}).get('hostname', 'Default Hostname')
        except KeyError:
            title = "Unknown Hostname"
        return title

    def setup_output_console(self):
        # Initialize output console
        self.output_console = QTextEdit()
        self.output_console.setReadOnly(True)
        self.container_layout.addWidget(self.output_console)

    def setup_left_browser(self, session_id):
        self.session_id = session_id

        sftp_current_creds[self.session_id]['current_local_directory'] = os.getcwd()
        try:
            self.left_browser = FileBrowser("Local Files", self.session_id)
            self.left_browser.table.setFocusPolicy(Qt.StrongFocus)
            self.left_browser.message_signal.connect(self.update_console)
            self.container_layout.addWidget(self.left_browser)

        except Exception as e:
            pass

    def setup_right_browser(self, session_id):
        self.session_id = session_id
        try:
            self.right_browser = RemoteFileBrowser(title=self.title, session_id=self.session_id)
            self.right_browser.table.setFocusPolicy(Qt.StrongFocus)
            self.right_browser.message_signal.connect(self.update_console)

        except Exception as e:
            pass

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
            self.port_selector.setText(port)
        else:
            self.username.clear()
            self.password.clear()
            self.port_selector.clear()

    def removeTab(self, session_id):
        self.tabWidget.removeTab( self.tabs[session_id] )
        del self.tabs[session_id]  # Remove the reference from the list
        del sftp_current_creds[self.session_id]

    def on_value_changed(self, value):
        global MAX_TRANSFERS
        MAX_TRANSFERS = value

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
        # Initialize the dialog (if it's a popup dialog)
        # Connect the dialog's signals to appropriate slots
        # Initialize the container widget for the tab
        editDialogContainer = EditDialogContainer(self.host_data)
        editDialogContainer.editDialog.entryDoubleClicked.connect(self.onEntryDoubleClicked)

        # Add the container as a new tab
        self.tab_widget.addTab(editDialogContainer, "Edit Host Data")

        # Optionally, set the newly added tab as the current tab
        self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)

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

    def clear_queue_clicked(self):
        self.clear_queue(sftp_queue)
        self.output_console.append("queue cleared")

    def transfers_button_clicked(self):
        self.transfers_message.showhide.emit()

    def update_console(self, message):
        # Update the console with the received message
        self.output_console.append(message)

    def connect_button_pressed(self):
        # Call the connect method
        self.connect()

    def connect(self, hostname="localhost", username="guest", password="guest", port="22"):
        self.session_id = create_random_integer()

        if hostname == "localhost":
            if self.hostname_combo.currentText():
                self.temp_hostname = self.hostname_combo.currentText()
        else:
            self.temp_hostname = hostname

        if username == "guest":
            if self.username.text():
                self.temp_username = self.username.text()
        else:
            self.temp_username = username

        if password == "guest":
            if self.password.text():
                self.temp_password = self.password.text()
        else:
            self.temp_password = password

        if self.port_selector.text():
            self.temp_port = self.port_selector.text()
        else:
            self.temp_port = port

        # Create a new QWidget as a container for both the file table and the output console
        self.container_widget = QWidget()

        sftp_current_creds[self.session_id] = {
            'current_local_directory': '.',
            'current_remote_directory': '.',
            'hostname' : self.temp_hostname,
            'username' : self.temp_username,
            'password' : self.temp_password,
            'port' : self.temp_port, }

        self.YouAddTab(self.session_id, self.container_widget, self.use_terminal)

        return self.session_id

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
        add_sftp_job(".", False, ".", False, "localhost", "guest", "guest", 69, "end", 69)

def main():
    def hide_transfers_window():
        if not hasattr(hide_transfers_window, "transfers_hidden"):
            hide_transfers_window.transfers_hidden = 1  # Initialize it once
            background_thread_window.hide()
        elif hide_transfers_window.transfers_hidden == 0:
            background_thread_window.hide()
            hide_transfers_window.transfers_hidden = 1
        elif hide_transfers_window.transfers_hidden == 1:
            background_thread_window.show()
            hide_transfers_window.transfers_hidden = 0

    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # create the window we show the statuses of active transfers in, this is for downloads/uploads but also any background event like fetching a directory listing etc
    background_thread_window = BackgroundThreadWindow()
    background_thread_window.setWindowTitle("Transfer Queue")
    background_thread_window.show()

    # create the main window of the application
    main_window = MainWindow()
    main_window.setWindowTitle("FTP/SFTP Client")
    main_window.resize(800, 600)
    main_window.show()
    main_window.backgroundThreadWindow = background_thread_window
    main_window.transfers_message.showhide.connect(hide_transfers_window)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
