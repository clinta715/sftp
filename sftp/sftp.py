from icecream import ic
import sys
import base64
import os
import json
import shutil
import paramiko
import queue
import stat
from datetime import datetime
import enum
# from qtconsole.rich_jupyter_widget import RichJupyterWidget
# from qtconsole.inprocess import QtInProcessKernelManager
from PyQt5.QtWidgets import QPlainTextEdit,QTableView, QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog, QListWidget, QTextEdit, QMessageBox, QInputDialog, QMenu, QCompleter, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QSizePolicy, QDialog, QStyledItemDelegate, QSpinBox,QTabWidget
from PyQt5.QtCore import QVariant,QAbstractTableModel,QModelIndex,QThreadPool, QRunnable, pyqtSignal, QTimer, QObject, QCoreApplication, QDateTime, Qt, QEventLoop,pyqtSlot
from PyQt5 import QtCore
from stat import S_ISDIR
from pathlib import Path
# from qtermwidget import QTermWidget

MAX_HOST_DATA_SIZE = 10  # Set your desired maximum size

class SIZE_UNIT(enum.Enum):
    BYTES = 1
    KB = 2
    MB = 3
    GB = 4

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

sftp_queue = queue.Queue()
response_queues = {}
sftp_current_creds = {}

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

class FileTableModel(QAbstractTableModel):
    def __init__(self, session_id):
        super().__init__()
        global sftp_current_creds
        self.file_list = []
        self.session_id = session_id
        # Convert string to Path object if necessary
        sftp_current_creds[self.session_id]['current_local_directory'] = os.getcwd()
        self.directory = Path(sftp_current_creds[self.session_id]['current_local_directory'])
        self.column_names = ['Name', 'Size', 'Permissions', 'Modified']
        self.get_files()

    def is_remote_browser(self):
        # dummy function in local-files portion of code
        return False

    def get_files(self):
        ic("FileTableModel get files")
        self.directory = Path(sftp_current_creds[self.session_id]['current_local_directory'])

        # List all files and directories in the specified path
        items = list(self.directory.iterdir())

        # Prepare a list to store file information
        self.beginResetModel()
        self.file_list.clear()

        # Add the '..' entry to represent the parent directory
        # Assuming that size, permissions, and modified_time for '..' are not relevant, set them to default values
        self.file_list.append(["..", 0, "----", "----"])

        for item in items:
            # Get file name
            try:
                name = item.name
            except Exception as e:
                name = None

            # Get file size
            try:
                size = item.stat().st_size
            except Exception as e:
                size = None

            # Get file permissions
            try:
                permissions = oct(item.stat().st_mode)[-4:]
            except Exception as e:
                permissions = None

            # Get file modification time and convert it to a readable format
            try:
                modified_time = datetime.fromtimestamp(item.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            except Exception as e:
                modified_time = None

            # Append the file information to the list
            self.file_list.append([name, size, permissions, modified_time])

        # Emit signal to update the view
        top_left = self.createIndex(0, 0)  # Top left cell of the table
        bottom_right = self.createIndex(self.rowCount() - 1, self.columnCount() - 1)  # Bottom right cell
        self.dataChanged.emit(top_left, bottom_right)
        self.endResetModel()
        self.layoutChanged.emit()

    def rowCount(self, parent=QModelIndex()):
        # Return the number of items in your files list
        return len(self.file_list)

    def columnCount(self, parent=QModelIndex()):
        # Return the length of the column_names array
        return len(self.column_names)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.file_list)):
            return QVariant()

        # Get the file information for the current row
        file_info = self.file_list[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            if column == 0:
                # Name
                try:
                    return file_info[0]
                except Exception as e:
                    return None
            elif column == 1:
                # Size
                try:
                    return str(file_info[1])
                except Exception as e:
                    return None
            elif column == 2:
                # Permissions
                try:
                    return file_info[2]
                except Exception as e:
                    return None
            elif column == 3:
                # Modified Date
                try:
                    return file_info[3]
                except Exception as e:
                    return None
        return QVariant()

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if section < len(self.column_names):
                return self.column_names[section]
        return None

    def sort(self, column, order):
        self.layoutAboutToBeChanged.emit()

        # Define custom sorting for each column
        if column == 0:
            # Sort by Name (String)
            try:
                self.file_list.sort(key=lambda file_info: file_info[0], reverse=(order == Qt.DescendingOrder))
            except Exception as e:
                pass
        elif column == 1:
            # Sort by Size (Numeric)
            try:
                self.file_list.sort(key=lambda file_info: int(file_info[1]), reverse=(order == Qt.DescendingOrder))
            except Exception as e:
                pass
        elif column == 2:
            # Sort by Permissions (String or Numeric, depending on representation)
            try:
                self.file_list.sort(key=lambda file_info: file_info[2], reverse=(order == Qt.DescendingOrder))
            except Exception as e:
                pass
        elif column == 3:
            # Sort by Modified Date (Date or Timestamp)
            # Assuming file_info[3] is a string representation of date, you might need to convert it to a datetime object
            # for proper sorting. This example assumes it's already a sortable format.
            try:
                self.file_list.sort(key=lambda file_info: file_info[3], reverse=(order == Qt.DescendingOrder))
            except Exception as e:
                pass

        self.layoutChanged.emit()

class RemoteFileTableModel(QAbstractTableModel):
    def __init__(self, session_id, parent=None):
        super().__init__(parent)  # Simplified form in Python 3
        self.session_id = session_id
        self.file_list = []  # Initialize as an empty list
        self.column_names = ['Name', 'Size', 'Permissions', 'Modified']
        self.get_files()

    def is_remote_browser(self):
        return True

    def rowCount(self, parent=QModelIndex()):
        # Return the number of files
        return len(self.file_list)

    def columnCount(self, parent=QModelIndex()):
        # Return the number of columns
        return len(self.column_names)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.file_list)):
            return QVariant()

        try:
            file = self.file_list[index.row()]
        except Exception as e:
            pass

        column = index.column()

        if role == Qt.DisplayRole:
            if column == 0:
                try:
                    return file[0]  # name
                except Exception as e:
                    pass
                    return ""
            elif column == 1:
                try:
                    return str(file[1])  # size
                except Exception as e:
                    pass
                    return ""
            elif column == 2:
                try:
                    return file[2]  # permissions
                except Exception as e:
                    pass
                    return ""
            elif column == 3:
                try:
                    return file[3]  # modified_date
                except Exception as e:
                    pass
                    return ""
        return QVariant()

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.column_names[section]
        return QVariant()

    def sort(self, column, order):
        self.layoutAboutToBeChanged.emit()

        if column == 0:
            # Sort by file name
            try:
                self.file_list.sort(key=lambda x: x[0], reverse=(order == Qt.DescendingOrder))
            except Exception as e:
                pass
        elif column == 1:
            # Sort by file size
            try:
                self.file_list.sort(key=lambda x: x[1], reverse=(order == Qt.DescendingOrder))
            except Exception as e:
                pass
        elif column == 2:
            # Sort by file permissions
            try:
                self.file_list.sort(key=lambda x: x[2], reverse=(order == Qt.DescendingOrder))
            except Exception as e:
                pass
        elif column == 3:
            # Sort by modified date
            try:
                self.file_list.sort(key=lambda x: x[3], reverse=(order == Qt.DescendingOrder))
            except Exception as e:
                pass

        ic("Emitting layoutchanged")
        self.layoutChanged.emit()

    def get_files(self):
        """
        Fetches file attributes from the specified path using the given SFTP connection.
        :param sftp: Paramiko SFTP client object
        :param path: Path to the directory on the remote server
        """
        # List all files and directories in the specified path
        items = self.sftp_listdir_attr(sftp_current_creds[self.session_id]['current_remote_directory'])
        # Clear the existing file list
        # Inform the view that the model is about to be reset
        self.beginResetModel()
        self.file_list.clear()

        # Add the '..' entry to represent the parent directory
        # Assuming that size, permissions, and modified_time for '..' are not relevant, set them to default values
        self.file_list.append(("..", 0, "----", "----"))

        for item in items:
            # Get file name
            try:
                name = item.filename
            except Exception as e:
                name = ""

            # Get file size
            try:
                size = item.st_size
            except Exception as e:
                size = 0

            # Get file permissions (convert to octal string)
            try:
                permissions = oct(item.st_mode)[-4:]
            except Exception as e:
                permissions = ""

            # Get file modification time and convert it to a readable format
            try:
                modified_time = QDateTime.fromSecsSinceEpoch(item.st_mtime).toString(Qt.ISODate)
            except Exception as e:
                modified_time = ""

            # Append the file information to the list
            self.file_list.append((name, size, permissions, modified_time))

        # Emit dataChanged for the entire range of data
        top_left = self.createIndex(0, 0)  # Top left cell of the table
        bottom_right = self.createIndex(self.rowCount() - 1, self.columnCount() - 1)  # Bottom right cell
        self.dataChanged.emit(top_left, bottom_right)
        self.endResetModel()
        self.layoutChanged.emit()

    def non_blocking_sleep(self, ms):
        # sleep function that shouldn't block any other threads
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec_()

    def sftp_listdir_attr(self, remote_path):
        job_id = create_random_integer()
        response_queues[job_id] = queue.Queue()

        # the slashes/backslashes stuff is an attempt at windows compatibility
        add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "listdir_attr", job_id )

        while response_queues[job_id].empty():
            self.non_blocking_sleep(100)  # Sleeps for 1000 milliseconds (1 second)

        response = response_queues[job_id].get_nowait()

        if response == "error":
            error = response_queues[job_id].get_nowait()
            diag = f"RemoteFileTableModel sftp_listdir_attr() {error}"
            # always 2 responses on stack, if its an error, get message
            f = False
        else:
            # if its not an error its a success and heres the list
            list = response_queues[job_id].get_nowait()
            f = True

        del response_queues[job_id]
        if f:
            return list
        else:
            return f

class Browser(QWidget):
    def __init__(self, title, session_id, parent=None):
        global sftp_current_creds
        super().__init__(parent)  # Initialize the QWidget parent class
        self.title = title
        self.model = None
        self.session_id = session_id
        self.user_choice = None
        self.init_global_creds()
        self.init_ui()

    def init_global_creds(self):
        creds = sftp_current_creds.get(self.session_id, {})
        self.init_hostname = creds.get('hostname')
        self.init_username = creds.get('username')
        self.init_password = creds.get('password')
        self.init_port = creds.get('port')

    # Define a signal for sending messages to the console
    message_signal = pyqtSignal(str)

    def init_ui(self):
        self.layout = QVBoxLayout()
        self.label = QLabel(self.title)
        self.layout.addWidget(self.label)

        # Initialize and set the model for the table
        self.table = QTableView()

        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        # Enable sorting
        self.table.setSortingEnabled(True)

        # Connect signals and slots
        self.table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.table.doubleClicked.connect(self.double_click_handler)
        self.table.customContextMenuRequested.connect(self.context_menu_handler)

        # UI configuration
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.sortByColumn(0, Qt.AscendingOrder)

        self.layout.addWidget(self.table)  # Correctly add the table to the layout

        # Add the table and status bar to the layout
        self.progressBar = QProgressBar()
        self.layout.addWidget(self.progressBar)

        # Set the main layout of the widget
        self.setLayout(self.layout)

    def split_path(self, path):
        if "\\" in path:
            # Use "\\" as the separator
            head, tail = path.rsplit("\\", 1)
        elif "/" in path:
            # Use "/" as the separator
            head, tail = path.rsplit("/", 1)
        else:
            # No "\\" or "/" found, assume the entire string is the head
            head, tail = path, ""

        return head, tail

    def waitjob(self, job_id):
        # Initialize the progress bar
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)

        progress_value = 0
        while response_queues[job_id].empty():
            # Increment progress by 10%, up to 100%
            progress_value = min(progress_value + 10, 100)
            self.progressBar.setValue(progress_value)

            # Sleep and process events to keep UI responsive
            self.non_blocking_sleep(100)
            QApplication.processEvents()  # Process any pending GUI events

        # Reset the progress bar after completion
        self.progressBar.setValue(100)
        self.progressBar.setRange(0, 100)

        # Return after the job is done
        return

    def sftp_mkdir(self, remote_path):
        job_id = create_random_integer()
        response_queues[job_id] = queue.Queue()

        add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "mkdir", job_id )

        self.waitjob(job_id)

        response = response_queues[job_id].get_nowait()

        if response == "error":
            error = response_queues[job_id].get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_mkdir() {error}")
            f = False
        else:
            # if its a success then we dont care about the response and the queue will be deleted
            f = True

        self.model.get_files()
        del response_queues[job_id]
        return f

    def sftp_rmdir(self, remote_path):
        job_id = create_random_integer()
        response_queues[job_id] = queue.Queue()

        add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "rmdir", job_id )

        self.waitjob(job_id)
        response = response_queues[job_id].get_nowait()

        if response == "error":
            error = response_queues[job_id].get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_rmdir() {error}")
            f = False
        else:
            f = True

        self.model.get_files()
        del response_queues[job_id]
        return f

    def sftp_remove(self, remote_path ):
        job_id = create_random_integer()
        response_queues[job_id] = queue.Queue()

        add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "remove", job_id )

        self.waitjob(job_id)
        response = response_queues[job_id].get_nowait()

        if response == "error":
            error = response_queues[job_id].get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_remove() {error}")
            f = False
        else:
            f = True

        self.model.get_files()
        del response_queues[job_id]
        return f

    def sftp_listdir(self, remote_path ):
        job_id = create_random_integer()
        diag = f"FileBrowser sftp_listdir() job_id {job_id} session_id {self.session_id} remote_path {remote_path}"
        ic(diag)
        response_queues[job_id] = queue.Queue()

        add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "listdir", job_id )

        self.progressBar.setRange(0, 0)
        while response_queues[job_id].empty():
            self.non_blocking_sleep(100)  # Sleeps for 1000 milliseconds (1 second)
        response = response_queues[job_id].get_nowait()
        self.progressBar.setRange(0, 100)

        if response == "error":
            error = response_queues[job_id].get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_listdir() {error}")
            ic(error)
            f = False
        else:
            list = response_queues[job_id].get_nowait()
            f = True

        del response_queues[job_id]
        if f:
            return list
        else:
            return f

    def non_blocking_sleep(self, ms):
        # special sleep function that can be used by a background/foreground thread, without causing a hang

        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec_()

    def sftp_listdir_attr(self, remote_path ):
        # get remote directory listing with attributes from the remote_path

        job_id = create_random_integer()
        response_queues[job_id] = queue.Queue()
        diag = f"FileBrowser sftp_listdir_attr() job_id {job_id} session_id {self.session_id} remote_path {remote_path}"
        ic(diag)
        ic(sftp_current_creds[self.session_id])

        add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "listdir_attr", job_id )

        self.waitjob(job_id)
        response = response_queues[job_id].get_nowait()

        if response == "error":
            error = response_queues[job_id].get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_listdir_attr() {error}")
            ic(error)
            f = False
        else:
            list = response_queues[job_id].get_nowait()
            f = True

        del response_queues[job_id]
        if f:
            return list
        else:
            return f

    def on_header_clicked(self, logicalIndex):
        # Check the current sort order and toggle it
        # not the best, should really be revised 
        order = Qt.DescendingOrder if self.table.horizontalHeader().sortIndicatorOrder() == Qt.AscendingOrder else Qt.AscendingOrder
        self.table.sortByColumn(logicalIndex, order)

    def is_remote_directory(self, remote_path ):
        # check to see if remote_path is in fact a file or a directory on the current remote connection 

        job_id = create_random_integer()
        response_queues[job_id] = queue.Queue()

        try:
            add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "stat", job_id )

            self.waitjob(job_id)
            response = response_queues[job_id].get_nowait()

            if not response == "error":
                attributes = response_queues[job_id].get_nowait()
                is_directory = S_ISDIR(attributes.st_mode)
            else:
                error = response_queues[job_id].get_nowait()
                self.message_signal.emit(f"FileBrowser is_remote_directory() {error}")
                is_directory = False

        except Exception as e:
            self.message_signal.emit(f"FileBrowser is_remote_directory() {e}")
            is_directory = False

        finally:
            del response_queues[job_id]
            return is_directory

    def is_remote_file(self, remote_path ):
        # check to see if remote_path is in fact a file or a directory on the current remote connection

        job_id = create_random_integer()
        response_queues[job_id] = queue.Queue()

        try:
            add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "stat", job_id )

            self.waitjob(job_id)
            response = response_queues[job_id].get_nowait()

            if not response == "error":
                attributes = response_queues[job_id].get_nowait()
                is_directory = S_ISDIR(attributes.st_mode)
            else:
                error = response_queues[job_id].get_nowait()
                raise error

        except FileNotFoundError:
            # If the file doesn't exist, treat it as not a file
            return False

        except Exception as e:
            # Handle other exceptions (e.g., permission denied, etc.) if needed
            self.message_signal.emit(f"FileBrowser is_remote_file() {e}")
            return False

        finally:
            del response_queues[job_id]
            return is_directory

    def focusInEvent(self, event):
        self.setStyleSheet("""
            QTableWidget {
            background-color: #ffffff; /* Set background color */
            color: white;  /* Text color */
            border: 1px solid #cccccc; /* Add a thin border */
            selection-background-color: #e0e0e0; /* Set background color for selected items */
            }
        """)
        self.label.repaint()  # Force a repaint

    def focusOutEvent(self, event):
        self.setStyleSheet("""
            QTableWidget {
            background-color: #777777; /* Set background color */
            color: gray;  /* Text color */
            border: 1px solid #999999; /* Add a thin border */
            selection-background-color: #909090; /* Set background color for selected items */
            }
        """)
        self.label.repaint()  # Force a repaint

    def prompt_and_create_directory(self):
        # Prompt the user for a new directory name
        directory_name, ok = QInputDialog.getText(
            None,
            'Create New Directory',
            'Enter the name of the new directory:'
        )

        if ok and directory_name:
            directory_path = os.path.join(sftp_current_creds[self.session_id]['current_local_directory'], directory_name)

            try:
                # Attempt to create the directory locally
                os.makedirs(directory_path)
                self.message_signal.emit(f"Directory '{directory_path}' created successfully.")

            except Exception as e:
                QMessageBox.critical(None, 'Error', f"Error creating directory: {e}")
                self.message_signal.emit(f"Error creating directory: {e}")

            finally:
                self.model.get_files()

    def change_directory(self, path ):
        # this is a function to change the current LOCAL working directory, it also uses this moment to refresh the local file list

        try:
            # Local file browser
            os.chdir(path)
            sftp_current_creds[self.session_id]['current_local_directory'] = os.getcwd()
            self.model.get_files()  # Update local file browser with new directory contents
        except Exception as e:
            # Append error message to the output_console
            self.message_signal.emit(f"change_directory() {e}")

    def double_click_handler(self, index):
        # this function tries to figure out, more or less sans a lot of context, what 'index' is pointing at and then, what to do with it
        # my logic here was, if its a directory change to it, if its a file transfer it
        # if its a local file, probably want to upload it, if its a remote file, probably want to download it

        if index.isValid():
            # Retrieve the data from the model
            path = self.model.data(index, Qt.DisplayRole)
            # Now you can use 'text' as needed

        try:
            if path == "..":
                head, tail = self.split_path(sftp_current_creds[self.session_id]['current_local_directory'])
                new_path = head
                ic(new_path)
            else:
                new_path = os.path.join(sftp_current_creds[self.session_id]['current_local_directory'], path)  # Assuming the text of the item contains the file path

            # Check if the item is a directory
            is_directory = os.path.isdir(new_path)
            if is_directory:
                # Change the current working directory or perform other actions
                self.change_directory(new_path)
            else:
                # Upload the file to the remote server
                remote_path, _ = QFileDialog.getSaveFileName(self, "Select Remote Location", os.path.basename(path))
                if remote_path:
                    self.upload_download(new_path)

        except Exception as e:
            # Append error message to the output_console
            self.message_signal.emit(f"double_click_handler() {e}")

    def context_menu_handler(self, point):
        # If point is not provided, use the center of the list widget
        if not point:
            point = self.file_list.rect().center()

        # Get the currently focused widget
        current_browser = self.focusWidget()
        if current_browser is not None:
            menu = QMenu(self)
            # Add actions to the menu
            remove_dir_action = menu.addAction("Remove Directory")
            change_dir_action = menu.addAction("Change Directory")  # New action
            upload_download_action = menu.addAction("Upload/Download")
            prompt_and_create_directory = menu.addAction("Create Directory")

            # Connect the actions to corresponding methods
            remove_dir_action.triggered.connect(self.remove_directory_with_prompt)
            change_dir_action.triggered.connect(self.change_directory_handler)  # Connect to the new method
            upload_download_action.triggered.connect(self.upload_download)
            prompt_and_create_directory.triggered.connect(self.prompt_and_create_directory)

            # Show the menu at the cursor position
            menu.exec_(current_browser.mapToGlobal(point))

    def upload_download(self):
        # based on what the user clicked, let's decide if it's a local file needing uploading or a remote file needing downloading

        current_browser = self.focusWidget()
        # did they click the local or remote browser

        if current_browser is not None and isinstance(current_browser, QTableView):
            index = current_browser.currentIndex()
            # what thing did they click in that browser
            if index.isValid():
                # and now, what is that thing?!
                selected_item_text = current_browser.model().data(index, Qt.DisplayRole)

                if selected_item_text:
                    # Construct the full path of the selected item
                    selected_path = os.path.join(sftp_current_creds[self.session_id]['current_local_directory'], selected_item_text)

                    try:
                        remote_entry_path = os.path.join( sftp_current_creds[self.session_id]['current_remote_directory'], selected_item_text )
                        ic(remote_entry_path, selected_item_text, selected_path)

                        if os.path.isdir(selected_path):
                            # Upload a local directory to the remote server
                            self.message_signal.emit(f"Uploading directory: {selected_path}")
                            self.upload_directory(selected_path, remote_entry_path)
                        else:
                            # Upload a local file to the remote server
                            self.message_signal.emit(f"Uploading file: {selected_path}")
                            job_id = create_random_integer()
                            queue_item = QueueItem(os.path.basename(selected_path), job_id)
                            queue_display.append(queue_item)

                            # Assuming add_sftp_job handles the actual upload process
                            add_sftp_job(selected_path, False, remote_entry_path.replace("\\", "/"), True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "upload", job_id)
                    except Exception as e:
                        self.message_signal.emit(f"upload_download() {e}")
                else:
                    self.message_signal.emit("Invalid item or empty path.")
            else:
                self.message_signal.emit("No item selected or invalid index.")
        else:
            self.message_signal.emit("Current browser is not a valid QTableView.")

    def upload_directory(self, source_directory, destination_directory):
        self.always_continue_upload = False

        try:
            remote_folder = destination_directory

            target_exists = self.sftp_exists(remote_folder)

            if target_exists and self.is_remote_directory(remote_folder) and not self.always_continue_upload:
                response = self.show_prompt_dialog(f"The folder {remote_folder} already exists. Do you want to continue uploading?", "Upload Confirmation")

                if response == QMessageBox.No:
                    # User chose not to continue
                    return
                elif response == QMessageBox.Yes:
                    # User chose to continue
                    pass  # Continue with the upload
                elif response == QMessageBox.YesToAll:
                    # User chose to always continue
                    self.always_continue_upload = True
                else:
                    # User closed the dialog
                    return
            else:
                try:
                    success = self.sftp_mkdir(remote_folder.replace("\\", "/")) 
                    if not success or self.always_continue_upload:
                        self.message_signal.emit(f"sftp_mkdir() error creating {remote_folder} but always_continue_upload is {self.always_continue_upload}")
                        return
                except Exception as e:
                    self.message_signal.emit(f"{e}")
                    ic(e)

            local_contents = os.listdir(source_directory)

            for entry in local_contents:
                entry_path = os.path.join(source_directory, entry)
                ic(entry_path)
                remote_entry_path = os.path.join(remote_folder, entry)
                ic(remote_entry_path)

                job_id = create_random_integer()

                if os.path.isdir(entry_path):
                    queue_item = QueueItem( os.path.basename(entry_path), job_id )
                    queue_display.append(queue_item)
                    self.sftp_mkdir(remote_entry_path.replace("\\", "/"))
                    self.upload_directory(entry_path, remote_entry_path.replace("\\", "/"))
                else:
                    self.message_signal.emit(f"{entry_path}, {remote_entry_path}")

                    queue_item = QueueItem( os.path.basename(entry_path), job_id )
                    queue_display.append(queue_item)

                    add_sftp_job(entry_path, False, remote_entry_path.replace("\\", "/"), True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "upload", job_id)

        except Exception as e:
            self.message_signal.emit(f"upload_directory() {e}")
            ic(e)

    def show_prompt_dialog(self, text, title):
        dialog = QMessageBox(self.parent())
        dialog.setWindowTitle(title)
        dialog.setText(text)
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll)
        dialog.setDefaultButton(QMessageBox.Yes)

        return dialog.exec_()

    def sftp_exists(self, path):
        job_id = create_random_integer()
        response_queues[job_id] = queue.Queue()

        try:
            add_sftp_job(path.replace("\\", "/"), True, path.replace("\\", "/"), True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "stat", job_id )

            self.waitjob(job_id)
            response = response_queues[job_id].get_nowait()

            if response == "error":
                error = response_queues[job_id].get_nowait() # get error message
                self.message_signal.emit(f"sftp_exists() {error}")
                raise error
            else: # success means what it is it exists
                exist = True

        except Exception as e:
            diag = f"FileBrowser sftp_exists() {e}"
            ic(diag)
            self.message_signal.emit(f"sftp_exists() {e}")
            exist = False

        finally:
            del response_queues[job_id]
            return exist

    def change_directory_handler(self):
        selected_path, ok = QInputDialog.getText(self, 'Input Dialog', 'Enter directory name:')

        if not ok:
            return

        try:
            is_directory = os.path.isdir(selected_path)

            if is_directory:
                # Call the method to change the directory
                self.change_directory(selected_path)

        except Exception as e:
            # Append error message to the output_console
            self.message_signal.emit(f"change_directory_handler() {e}")

        finally:
            self.model.get_files()

class FileBrowser(Browser):
    def __init__(self, title, session_id, parent=None):
        super().__init__(title, session_id, parent)  # Initialize the FileBrowser parent class
        self.model = FileTableModel(self.session_id)
        self.table.setModel(self.model)

        # Set horizontal scroll bar policy for the entire table
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # Resize the first column based on its contents
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)

    def remove_directory_with_prompt(self, local_path=None):
        # for removing LOCAL directories
        if local_path == None or local_path == False:
            current_browser = self.focusWidget()
            if current_browser is not None:
                current_index = current_browser.currentIndex()
                if current_index.isValid():
                    # Assuming the first column holds the item text you need
                    selected_item = current_browser.model().data(current_index, Qt.DisplayRole)
                    local_path = selected_item
                    if selected_item is not None:
                        local_path = os.path.join( sftp_current_creds[self.session_id]['current_local_directory'], selected_item )
                        ic(local_path)
            else:
                return

        try:
            # Check if the path exists locally
            if not os.path.exists(local_path):
                self.message_signal.emit(f"Path '{local_path}' not found locally.")
                return

            # Check if it's a file
            if os.path.isfile(local_path):
                os.remove(local_path)
                self.message_signal.emit(f"File '{local_path}' removed successfully.")
                return

            # It's a directory, check if it has child items
            directory_contents = os.listdir(local_path)
            subdirectories = [entry for entry in directory_contents if os.path.isdir(os.path.join(local_path, entry))]
            files = [entry for entry in directory_contents if os.path.isfile(os.path.join(local_path, entry))]

            if subdirectories or files:
                # Directory has child items, prompt for confirmation using QMessageBox
                response = QMessageBox.question(
                    None,
                    'Confirmation',
                    f"The directory '{local_path}' contains subdirectories or files. Do you want to remove them all?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )

                if response == QMessageBox.No:
                    return

                # Recursively remove subdirectories
                for entry in subdirectories:
                    entry_path = os.path.join(local_path, entry)
                    self.remove_directory_with_prompt(entry_path)

                # Remove files
                for entry in files:
                    entry_path = os.path.join(local_path, entry)
                    os.remove(entry_path)

            # Remove the directory
            shutil.rmtree(local_path)
            self.model.get_files()

        except Exception as e:
            self.message_signal.emit(f"remove_directory_with_prompt() {e}")
            ic(e)

    def is_remote_browser(self):
        return False

class RemoteFileBrowser(FileBrowser):
    def __init__(self, title, session_id, parent=None):
        super().__init__(title, session_id, parent)  # Initialize the FileBrowser parent class
        self.model = RemoteFileTableModel(self.session_id)
        self.table.setModel(self.model)
        # Set horizontal scroll bar policy for the entire table
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # Resize the first column based on its contents
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)

    def is_remote_browser(self):
        return True

    def prompt_and_create_directory(self):
        # Prompt the user for a new directory name
        directory_name, ok = QInputDialog.getText(
            None,
            'Create New Directory',
            'Enter the name of the new directory:'
        )

        if ok and directory_name:
            try:
                # Attempt to create the directory locally
                self.sftp_mkdir(directory_name)
                self.message_signal.emit(f"'{directory_name}' created successfully.")
                self.model.get_files()
            except Exception as e:
                self.message_signal.emit(f"Error creating directory: {e}")

    def sftp_getcwd(self):
        job_id = create_random_integer()
        response_queues[job_id] = queue.Queue()

        ic("sftp_getcwd()")
        ic(self.session_id)

        add_sftp_job(sftp_current_creds[self.session_id]['current_remote_directory'], True, ".", True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "getcwd", job_id)

        self.waitjob(job_id)
        response = response_queues[job_id].get_nowait()

        if response == "error":
            response = response_queues[job_id].get_nowait()
            ic(response)
            new_path = None
        else:
            # if success, set our new remote working path to the newly created path path that we path'd pathily'
            new_path = response_queues[job_id].get_nowait()

        del response_queues[job_id]
        return new_path

    def change_directory(self, path ):
        job_id = create_random_integer()
        response_queues[job_id] = queue.Queue()
        if sftp_current_creds[self.session_id]['current_remote_directory'] == ".":
            sftp_current_creds[self.session_id]['current_remote_directory'] = self.sftp_getcwd()

        try:
            # Remote file browser
            if path == "..":
                head, tail = self.split_path(sftp_current_creds[self.session_id]['current_remote_directory'])
                new_path = head
            else:
                # Ensure there's a trailing slash at the end of the input path
                new_path = os.path.join(sftp_current_creds[self.session_id]['current_remote_directory'],path)

            # sessions are transient but lets make sure the folder exists
            add_sftp_job(new_path.replace("\\", "/"), True, new_path.replace("\\", "/"), True, sftp_current_creds[self.session_id]['hostname'], sftp_current_creds[self.session_id]['username'], sftp_current_creds[self.session_id]['password'], sftp_current_creds[self.session_id]['port'], "chdir", job_id)

            self.progressBar.setRange(0, 0)
            while response_queues[job_id].empty():
                self.non_blocking_sleep(100)  # Sleeps for 1000 milliseconds (1 second)
            response = response_queues[job_id].get_nowait()
            self.progressBar.setRange(0, 100)

            if response == "error":
                response = response_queues[job_id].get_nowait()
                ic(response)
                raise response
            else:
                # if success, set our new remote working path to the newly created path path that we path'd pathily'
                sftp_current_creds[self.session_id]['current_remote_directory'] = new_path

            self.message_signal.emit(f"{new_path}")
            self.model.get_files()
            self.table.viewport().update()
            f = True
        except Exception as e:
            # Emit the message signal
            self.message_signal.emit(f"change_directory() {e}")
            f = False

        finally:
            del response_queues[job_id]
            return f

    def double_click_handler(self, index):
        # ic("RemoteFileBrowser double_click_handler")
        try:
            if index.isValid():
                # Retrieve the file path from the model
                # ic("RemoteFileBrowser double_click_handler index.isValid()")
                temp_path = self.model.data(index, Qt.DisplayRole)
                ic(temp_path)

                if temp_path != "..":
                    # ic("RemoteFileBrowser double_click_handler temp_path != ..")
                    path = os.path.join( sftp_current_creds[self.session_id]['current_remote_directory'], temp_path )
                    if self.is_remote_directory(temp_path):
                        ic(temp_path)
                        self.change_directory(path.replace("\\", "/"))
                    elif self.is_remote_file(temp_path):
                        # ic("RemoteFileBrowser double_click_handler is_remote_file()")
                        local_path = QFileDialog.getSaveFileName(self, "Save File", os.path.basename(temp_path))[0]
                        if local_path:
                            # Assuming upload_download is a method to handle the download
                            self.upload_download(local_path)
                            # Emit a signal or log the download
                            self.message_signal.emit(f"Downloaded file: {path} to {local_path}")
                if temp_path == "..":
                    # ic("RemoteFileBrowser double_click_handler temp_path == ..")
                    # head, tail = self.split_path(sftp_current_creds[self.session_id]['current_remote_directory'])
                    self.change_directory(temp_path)

                return True
            else:
                return False

        except Exception as e:
            ic(e)
            return False

    def change_directory_handler(self):
        selected_item, ok = QInputDialog.getText(self, 'Input Dialog', 'Enter directory name:')

        if not ok:
            return

        if self.is_remote_directory(selected_item):
            self.change_directory(selected_item)

    def remove_trailing_dot(self, s):
        if s.endswith('/.'):
            return s[:-1]  # Remove the last character (dot)
        else:
            return s

    def remove_directory_with_prompt(self, remote_path=None):
        if remote_path == None or remote_path == False:
            current_browser = self.focusWidget()
            if current_browser is not None:
                current_index = current_browser.currentIndex()
                if current_index.isValid():
                    # Assuming the first column holds the item text you need
                    selected_item = current_browser.model().data(current_index, Qt.DisplayRole)
                    if sftp_current_creds[self.session_id]['current_remote_directory'] == '.':
                        temp_path = self.sftp_getcwd()
                    sftp_current_creds[self.session_id]['current_remote_directory'] = self.remove_trailing_dot(temp_path)
                    remote_path = os.path.join( sftp_current_creds[self.session_id]['current_remote_directory'], selected_item )
            else:
                return

        try:
            # Get attributes of directory contents
            directory_contents_attr = self.sftp_listdir_attr(remote_path)

            # Separate files and subdirectories
            subdirectories = [entry for entry in directory_contents_attr if stat.S_ISDIR(entry.st_mode)]
            files = [entry for entry in directory_contents_attr if stat.S_ISREG(entry.st_mode)]

            if subdirectories or files:
                response = QMessageBox.question(
                    None,
                    'Confirmation',
                    f"The directory '{remote_path}' contains subdirectories or files. Do you want to remove them all?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )

                if response == QMessageBox.No:
                    return
 
            # Remove files
            for entry in files:
                entry_path = os.path.join(remote_path, entry.filename)
                ic("Removing file:", entry_path)
                self.message_signal.emit(f"Removing file: {entry_path}")
                self.sftp_remove(entry_path)

            # Recursively remove subdirectories
            for entry in subdirectories:
                entry_path = os.path.join(remote_path, entry.filename)
                ic("Recursing into subdirectory:", entry_path)
                self.message_signal.emit(f"Recursing into subdirectory: {entry_path}")
                self.remove_directory_with_prompt(entry_path)


            # Remove the directory
            self.sftp_rmdir(remote_path)
            ic("Removing directory:", remote_path)
            self.message_signal.emit(f"Directory '{remote_path}' removed successfully.")
            self.model.get_files()

        except Exception as e:
            self.message_signal.emit(f"remove_directory_with_prompt() {e}")

    def upload_download(self):
        current_browser = self.focusWidget()

        if current_browser is not None and isinstance(current_browser, QTableView):
            index = current_browser.currentIndex()
            if index.isValid():
                selected_item_text = current_browser.model().data(index, Qt.DisplayRole)

                if selected_item_text:
                    selected_path = selected_item_text  # Assuming this is the full path or relative path

                    try:
                        # local_entry_path = os.path.join(os.getcwd(), os.path.basename(selected_path))
                        entry_path = os.path.join( sftp_current_creds[self.session_id]['current_remote_directory'], os.path.basename(selected_path))
                        local_path = os.path.join( os.getcwd(), os.path.basename(selected_path))

                        if self.is_remote_directory(entry_path):
                            # Download directory
                            self.download_directory(entry_path, local_path)
                        else:
                            # Download file
                            job_id = create_random_integer()
                            queue_item = QueueItem(entry_path, job_id)
                            queue_display.append(queue_item)

                            add_sftp_job(entry_path, True, local_path, False, self.init_hostname, self.init_username, self.init_password, self.init_port, "download", job_id)
                    except Exception as e:
                        self.message_signal.emit(f"upload_download() {e}")
            else:
                self.message_signal.emit("No item selected or invalid index.")
        else:
            self.message_signal.emit("Current browser is not a valid QTableView.")

    def download_directory(self, source_directory, destination_directory):
        try:
            # Create a local folder with the same name as the remote folder
            local_folder = os.path.join(destination_directory, os.path.basename(source_directory))

            if os.path.exists(local_folder):
                # Check if 'always' option was selected before
                if self.user_choice == 'always':
                    pass
                # If not, show the dialog with 'always' option
                response = QMessageBox.question(
                    self,
                    'Folder Exists',
                    f"The folder '{local_folder}' already exists. Do you want to proceed?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll,
                    QMessageBox.No
                )
                if response == QMessageBox.YesToAll:
                    self.user_choice = 'always'
                elif response == QMessageBox.No:
                    return
            else:
                self.message_signal.emit(f"mkdir {local_folder}")
                os.makedirs(local_folder, exist_ok=True)

            # List the contents of the remote directory
            directory_contents = self.sftp_listdir(source_directory.replace("\\", "/"))
            ic(directory_contents)

            # Download files and recurse into subdirectories
            for entry in directory_contents:
                entry_path = os.path.join(source_directory, entry)
                local_entry_path = os.path.join(local_folder, entry)

                # If it's a directory, recursively download its contents
                if self.is_remote_directory(entry_path.replace("\\", "/")):
                    self.message_signal.emit(f"download_directory() {entry_path}, {local_folder}")
                    self.download_directory(entry_path.replace("\\", "/"), local_folder)
                else:
                    # If it's a file, download it
                    ic("download_directory() is_remote_directory() no")
                    self.message_signal.emit(f"download_directory() {entry_path}, {local_entry_path}")

                    if os.path.exists(local_entry_path):
                        if self.user_choice == 'always':
                            pass
                            # If not, show the dialog with 'always' option
                        
                        # changed indent here after noting the 'pass' statement above... 
                        response = QMessageBox.question(
                            self,
                            'Folder Exists',
                            f"The folder '{local_folder}' already exists. Do you want to proceed?",
                            QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll,
                            QMessageBox.No
                        )
                        if response == QMessageBox.YesToAll:
                            self.user_choice = 'always'
                        elif response == QMessageBox.No:
                            return
                    try:
                        os.remove(local_entry_path.replace("\\","/"))
                    except Exception as e:
                        self.message_signal.emit(f"download_directory() {e}")
                        pass

                    self.message_signal.emit(f"download_directory() {entry_path}, {local_entry_path}")
                    job_id = create_random_integer()

                    queue_item = QueueItem( os.path.basename(entry_path), job_id )
                    queue_display.append(queue_item)

                    add_sftp_job(entry_path.replace("\\", "/"), True, local_entry_path, False, self.init_hostname, self.init_username, self.init_password, self.init_port, "download", job_id)

        except Exception as e:
            self.message_signal.emit(f"download_directory() {e}")
            ic(e)

class DownloadWorker(QRunnable):
    def __init__(self, transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command=None):
        super(DownloadWorker, self).__init__()
        self.transfer_id = transfer_id
        self._stop_flag = False
        self.signals = WorkerSignals()
        self.ssh = paramiko.SSHClient()
        self.is_source_remote = is_source_remote
        self.job_source = job_source
        self.job_destination = job_destination
        self.is_destination_remote = is_destination_remote
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.command = command

    def convert_unit(self, size_in_bytes: int, unit: SIZE_UNIT):
        # """Convert the size from bytes to
        # other units like KB, MB or GB
        # """
        if unit == SIZE_UNIT.KB:
            return size_in_bytes/1024
        elif unit == SIZE_UNIT.MB:
            return size_in_bytes/(1024*1024)
        elif unit == SIZE_UNIT.GB:
            return size_in_bytes/(1024*1024*1024)
        else:
            return size_in_bytes

    def progress(self, transferred: int, tobe_transferred: int):
        # """Return progress every 50 MB"""
        if self._stop_flag:
            raise Exception("Transfer interrupted")
        percentage = round((float(transferred) / float(tobe_transferred)) * 100)
        self.signals.progress.emit(self.transfer_id,percentage)

    def run(self):
        ic("download_thread() run")
        try:
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(self.hostname, self.port, self.username, self.password)
            self.sftp = self.ssh.open_sftp()
        except Exception as e:
            self.signals.message.emit(self.transfer_id,f"download_thread() {e}")
            return

        ic("download_thread() connected (probably)")
        if self.is_source_remote and not self.is_destination_remote:
            # Download from remote to local
            self.signals.message.emit(self.transfer_id,f"download_thread() {self.job_source},{self.job_destination}")
            try:
                self.sftp.get(self.job_source, self.job_destination, callback=self.progress)
            except:
                self.signals.message.emit(self.transfer_id,f"Transfer {self.transfer_id} was interrupted.")

            self.signals.finished.emit(self.transfer_id)

        elif self.is_destination_remote and not self.is_source_remote :
            # Upload from local to remote
            self.signals.message.emit(self.transfer_id,f"download_thread() {self.job_source},{self.job_destination}")
            try:
                self.sftp.put(self.job_source, self.job_destination, callback=self.progress)
            except:
                self.signals.message.emit(self.transfer_id,f"Transfer {self.transfer_id} was interrupted.")

        elif self.is_source_remote and self.is_destination_remote:
            # must be a mkdir
            try:
                if self.command == "mkdir":
                    ic("download_thread() mkdir")

                    try:
                        self.sftp.mkdir(self.job_destination)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_destination)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "listdir_attr":
                    diag = f"download_thread() trying listdir_attr {self.job_source}"
                    ic(diag)

                    try:
                        response = self.sftp.listdir_attr(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(response)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "listdir":
                    ic("download_thread() listdir")

                    try:
                        response = self.sftp.listdir(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(response)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "chdir":
                    ic("download_thread() chdir")

                    try:
                        self.sftp.chdir(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_source)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "rmdir":
                    ic("download_thread() rmdir")

                    try:
                        self.sftp.rmdir(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_source)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "stat":
                    ic("download_thread() stat")

                    try:
                        attr = self.sftp.stat(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(attr)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "remove":
                    ic("download_thread() remove")

                    try:
                        self.sftp.remove(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_source)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "getcwd":
                    ic("download_thread() getcwd")

                    try:
                        stdin, stdout, stderr = self.ssh.exec_command('cd {}'.format(self.job_source))
                        stdin, stdout, stderr = self.ssh.exec_command('pwd')
                        if stderr.read():
                            ic("Error:", stderr.read().decode())
                        getcwd_path = stdout.read().strip().decode()
                        # .replace("\\", "/")
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(getcwd_path)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

            except Exception as e:
                self.signals.message.emit(self.transfer_id, f"{self.command} operation failed: {e}")
                response_queues[self.transfer_id].put("error")
                response_queues[self.transfer_id].put(e)

            finally:
                self.sftp.close()
                self.ssh.close()

        self.signals.finished.emit(self.transfer_id)

    def stop_transfer(self):
        self._stop_flag = True
        self.signals.message.emit(self.transfer_id, f"Transfer {self.transfer_id} ends.")

class BackgroundThreadWindow(QMainWindow):
    def __init__(self):
        super(BackgroundThreadWindow, self).__init__()
        self.active_transfers = 0
        self.transfers = []
        self.init_ui()

    def init_ui(self):
        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        size_policy.setHorizontalStretch(1)
        size_policy.setVerticalStretch(1)

        self.layout = QVBoxLayout()

        self.list_widget = QListWidget()
        self.layout.addWidget(self.list_widget)

        self.text_console = QTextEdit()
        self.text_console.setReadOnly(True)  # Make the text console read-only
        self.text_console.setSizePolicy(size_policy)
        self.text_console.textChanged.connect(self.scroll_to_bottom)
        self.layout.addWidget(self.text_console)

        central_widget = QWidget()
        central_widget.setLayout(self.layout)
        self.setCentralWidget(central_widget)

        self.thread_pool = QThreadPool.globalInstance()
        # Setup a QTimer to periodically check the queue
        self.check_queue_timer = QTimer(self)
        self.check_queue_timer.timeout.connect(self.check_and_start_transfers)
        self.check_queue_timer.start(100)  # Check every 1000 ms (1 second)

    def remove_queue_item_by_id(self, id_to_remove):
        global queue_display

        # Iterate over the queue_display list and remove the item with the matching ID
        queue_display = [item for item in queue_display if item.id != id_to_remove]

        # Optionally, update the list widget after removal
        self.populate_queue_list()

    def populate_queue_list(self):
        global queue_display

        # Clear the list widget first
        self.list_widget.clear()

        # Iterate over the queue_display and add each filename to the list widget
        for item in queue_display:
            self.list_widget.addItem(item.name)

    def scroll_to_bottom(self):
        # Scroll to the bottom of the QTextEdit
        vertical_scroll_bar = self.text_console.verticalScrollBar()
        vertical_scroll_bar.setValue(vertical_scroll_bar.maximum())

    def check_and_start_transfers(self):
        global sftp_queue  # sftp_queue is a global variable

        # Check if more transfers can be started
        if sftp_queue.empty() or self.active_transfers == MAX_TRANSFERS:
            return
        else:
            job = sftp_queue.get_nowait()  # Wait for 5 seconds for a job

        self.populate_queue_list()

        if job.command == "end":
            self._stop_flag = 1
        else:
            hostname = job.hostname
            password = job.password
            port = job.port
            username = job.username
            command = job.command
            # response_queue = job.response_queue

            diag = f"{job.id} check and start transfers"
            ic(diag)
            self.start_transfer(job.id, job.source_path, job.destination_path, job.is_source_remote, job.is_destination_remote, hostname, port, username, password, command )

    def start_transfer(self, transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command):
        # Create a horizontal layout for the progress bar and cancel button
        hbox = QHBoxLayout()

        # Create the textbox
        textbox = QLineEdit()
        textbox.setReadOnly(True)  # Make it read-only if needed
        textbox.setText(os.path.basename(job_source))  # Set text if needed
        hbox.addWidget(textbox, 2)  # Add it to the layout with a stretch factor

        # Create the progress bar
        progress_bar = QProgressBar()
        hbox.addWidget(progress_bar, 3)  # Add it to the layout with a stretch factor of 3

        # Create the cancel button
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(lambda: self.transfer_finished(transfer_id))
        hbox.addWidget(cancel_button, 1)  # Add it to the layout with a stretch factor of 1

        # Add the horizontal layout to the main layout
        self.layout.addLayout(hbox)

        # Store references to the widgets for later use
        diag = f"{transfer_id} start transfer"
        ic(diag)
        new_transfer = Transfer(transfer_id=transfer_id, download_worker=DownloadWorker(transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command), active=True, hbox=hbox, progress_bar=progress_bar, cancel_button=cancel_button, tbox=textbox)
        diag = f"{new_transfer.transfer_id} id"
        ic(diag)

        # Create and configure the download worker
        new_transfer.download_worker.signals.progress.connect(lambda tid, val: self.update_progress(tid, val))
        new_transfer.download_worker.signals.finished.connect(lambda tid: self.transfer_finished(tid))
        new_transfer.download_worker.signals.message.connect(lambda tid, msg: self.update_text_console(tid, msg))

        self.transfers.append(new_transfer)
        # Start the download worker in the thread pool
        self.thread_pool.start(new_transfer.download_worker)
        self.active_transfers += 1

    def transfer_finished(self, transfer_id):
        # Find the transfer
        transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)

        if transfer is None:
            self.text_console.append(f"No transfer found with ID {transfer_id}")
            diag = f"{transfer_id} error"
            ic(diag)
            return

        # Deactivate the transfer
        transfer.active = False

        # Stop the download worker if it's active
        # if transfer.download_worker and not transfer.download_worker.isFinished():
        transfer.download_worker.stop_transfer()

        if transfer.tbox:
            transfer.tbox.deleteLater()
            transfer.tbox = None

        # Remove and delete the progress bar
        if transfer.progress_bar:
            transfer.progress_bar.deleteLater()
            transfer.progress_bar = None

        # Remove and delete the cancel button
        if transfer.cancel_button:
            transfer.cancel_button.deleteLater()
            transfer.cancel_button = None

        if transfer.hbox:  # Assuming each transfer has a reference to its QHBoxLayout
            # Find the index of the layout in the main layout and remove it
            index = self.layout.indexOf(transfer.hbox)
            if index != -1:
                layout_item = self.layout.takeAt(index)
                if layout_item:
                    widget = layout_item.widget()
                    if widget:
                        widget.deleteLater()

        # Remove the transfer from the list
        self.transfers = [t for t in self.transfers if t.transfer_id != transfer_id]
        self.text_console.append("Transfer removed from the transfers list.")
        self.remove_queue_item_by_id(transfer_id)
        self.active_transfers -= 1

    def update_text_console(self, transfer_id, message):
        if message:
            self.text_console.append(f"{message}")

    def update_progress(self, transfer_id, value):
        # Find the transfer with the given transfer_id
        transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)

        if transfer and transfer.progress_bar:
            # Update the progress bar's value
            transfer.progress_bar.setValue(value)
        else:
            self.text_console.append(f"update_progress() No active transfer found with ID {transfer_id}")

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
            diag = f"EditDialog connect_button_clicked() selected_items {selected_items}"
            ic(diag)

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

        ic("save_data() save the data")

        for row in range(self.table.rowCount()):
            if self.table.item(row, 0) == None:
                continue
            if self.table.item(row, 1) == None:
                continue
            if self.table.item(row, 2) == None:
                continue
            if self.table.item(row, 3) == None:
                continue
            ic("save_data() data will be saved")
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

    def save_data_to_file(self):
        # saves data from host_data to sftp.json
        self.save_data()
        with open("sftp.json", "w") as file:
            json.dump(self.host_data, file, indent=4)

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

    def onCloseClicked(self):
        # Do any necessary cleanup
        super().load_saved_data()

class CustomComboBox(QComboBox):
    editingFinished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()

class SshTerminalTab(QWidget):
    def __init__(self, session_id, parent=None):
        super().__init__(parent)
        self.session_id = session_id

        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        self.layout = QVBoxLayout(self)

        self.output_textedit = QPlainTextEdit(self)
        self.output_textedit.setReadOnly(True)
        self.output_textedit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.input_lineedit = QLineEdit(self)
        self.input_lineedit.returnPressed.connect(self.send_command)

        self.layout.addWidget(self.output_textedit)
        self.layout.addWidget(self.input_lineedit)

        self.load_credentials()

    def load_credentials(self):
        if self.session_id in sftp_current_creds:
            credentials = sftp_current_creds[self.session_id]
            self.connect_ssh(credentials['hostname'], credentials['username'], credentials['password'], credentials['port'])
        else:
            self.output_textedit.insertPlainText(f"Session ID '{self.session_id}' not found in credentials.\n")

    def connect_ssh(self, host, username, password, port):
        try:
            self.ssh_client.connect(host, username=username, password=password, port=port)
            self.output_textedit.insertPlainText("SSH connection established.\n")
        except Exception as e:
            self.output_textedit.insertPlainText(f"Error connecting to SSH: {e}\n")

    @pyqtSlot()
    def send_command(self):
        command = self.input_lineedit.text()
        self.input_lineedit.clear()

        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(command)
            output = stdout.read().decode()
            error = stderr.read().decode()

            if output:
                self.output_textedit.insertPlainText(output)
            if error:
                self.output_textedit.insertPlainText(error)
        except Exception as e:
            self.output_textedit.insertPlainText(f"Error executing command: {e}\n")

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
        self.load_queue_from_file()
        QCoreApplication.instance().aboutToQuit.connect(self.cleanup)
        self.hostnames = []
        self.sessions = []
        self.init_ui()

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
        # self.terminal_connect_button = QPushButton("Terminal Connect")

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
        self.load_saved_data()
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
        self.use_terminal = use_terminal
        # Create a container widget
        container_widget = QWidget()

        # Create a layout for the browsers
        browser_layout = QHBoxLayout()
        
        if not self.use_terminal:
            browser_layout.addWidget(self.left_browser)
            browser_layout.addWidget(self.right_browser)
        else:
            # Set up the terminal layout using QTermWidget
            self.tab1 = SshTerminalTab(self.session_id, container_widget)

        if not self.use_terminal:
            # Create the main layout
            main_layout = QVBoxLayout()
            main_layout.addLayout(browser_layout)
            main_layout.addWidget(self.output_console)

            # Set the main layout to the container widget
            container_widget.setLayout(main_layout)
            self.log_connection_success()
        else:
            # Create a layout for the container
            container_layout = QVBoxLayout(container_widget)
            container_layout.addWidget(self.tab1)
            self.tab1.connect_ssh(sftp_current_creds[self.session_id]['hostname'],
                                sftp_current_creds[self.session_id]['username'],
                                sftp_current_creds[self.session_id]['password'],
                                sftp_current_creds[self.session_id]['port'])
            
        return container_widget

    def closeTab(self, index):
        # Close the tab at the given index
        widget_to_remove = self.tab_widget.widget(index)
        self.tab_widget.removeTab(index)

        # Delete the widget if necessary
        widget_to_remove.deleteLater()

    def YouAddTab(self, session_id, widget, use_terminal=False):
        self.session_id = session_id
        self.use_terminal = use_terminal

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
            ic("Session ID not found in sftp_current_creds")
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
            ic(e)

    def setup_right_browser(self, session_id):
        self.session_id = session_id
        try:
            self.right_browser = RemoteFileBrowser(title=self.title, session_id=self.session_id)
            self.right_browser.table.setFocusPolicy(Qt.StrongFocus)
            self.right_browser.message_signal.connect(self.update_console)

        except Exception as e:
            error_message = f"Error setting up right browser: {e}"
            ic(error_message)

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
        ic(entry)
        hostname = entry.get("hostname", "localhost")
        username = entry.get("username", "guest")
        password = entry.get("password", "guest")
        port = entry.get("port", "22")

        self.connect(hostname=hostname, username=username, password=password, port=port)

    def save_queue_to_file(self):
        if not sftp_queue.empty():
            items = [job.to_dict() for job in list(sftp_queue.queue)]
            with open("sftp_queue.json", "w") as file:
                json.dump(items, file)

    def load_queue_from_file(self):
        try:
            with open("sftp_queue.json", "r") as file:
                items = json.load(file)
                for item in items:
                    job = SFTPJob.from_dict(item)
                    sftp_queue.put(job)

            # Delete the file after loading the queue
            os.remove("sftp_queue.json")

        except FileNotFoundError:
            pass  # File not found, start with an empty queue
        except json.JSONDecodeError:
            pass  # JSON decoding error, start with an empty queue
        except Exception as e:
            self.output_console.append(f"An error occurred while loading or deleting the file: {e}")
            # Handle other exceptions or log them as needed

    def closeEvent(self, event):
        # Assuming you have a reference to BackgroundThreadWindow instance
        if self.backgroundThreadWindow:
            self.backgroundThreadWindow.close()
        self.save_queue_to_file()
        event.accept()  # Accept the close event

    # Function to safely clear a queue
    def clear_queue(self, q):
        try:
            while True:  # Continue until an Empty exception is raised
                q.get_nowait()  # Remove an item from the queue
                q.task_done()  # Indicate that a formerly enqueued task is complete
        except Exception as e:
            ic(e)
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

    def terminal_connect_button_pressed(self):
        # Call the connect method
        self.connect(use_terminal=True)

    def connect(self, hostname="localhost", username="guest", password="guest", port="22", use_terminal=False):
        self.session_id = create_random_integer()
        self.use_terminal = use_terminal
        diag = f"connect() session_id {self.session_id}"
        ic(diag)

        if hostname == "localhost":
            if self.hostname_combo.currentText():
                self.temp_hostname = self.hostname_combo.currentText()
        else:
            self.temp_hostname = hostname
        ic(self.temp_hostname)

        if username == "guest":
            if self.username.text():
                self.temp_username = self.username.text()
        else:
            self.temp_username = username
        ic(self.temp_username)

        if password == "guest":
            if self.password.text():
                self.temp_password = self.password.text()
        else:
            self.temp_password = password
        ic(self.temp_password)

        if self.port_selector.text():
            self.temp_port = self.port_selector.text()
        else:
            self.temp_port = port
        ic(self.temp_port)

        # Create a new QWidget as a container for both the file table and the output console
        self.container_widget = QWidget()

        sftp_current_creds[self.session_id] = {
            'current_local_directory': '.',
            'current_remote_directory': '.',
            'hostname' : self.temp_hostname,
            'username' : self.temp_username,
            'password' : self.temp_password,
            'port' : self.temp_port, }

        ic(sftp_current_creds[self.session_id])

        self.YouAddTab(self.session_id, self.container_widget, self.use_terminal)

        return self.session_id

    def load_saved_data(self, filename="sftp.json"):
        try:
            with open(filename, "r") as file:
                data_loaded = json.load(file)

            # Resetting host_data to ensure it's empty before loading new data
            self.host_data = {
                "hostnames": {},
                "usernames": {},
                "passwords": {},
                "ports": {}
            }

            # Distribute the loaded data into respective dictionaries
            for hostname, details in data_loaded.items():
                decoded_password = base64.b64decode(details['password']).decode()
                self.host_data['hostnames'][hostname] = hostname
                self.host_data['usernames'][hostname] = details['username']
                self.host_data['passwords'][hostname] = decoded_password
                self.host_data['ports'][hostname] = details['port']

        except FileNotFoundError:
            ic("sftp.json file not found. Creating initial data.")
            # Handle the creation of initial data
            self.create_initial_data()
            self.load_saved_data()

        except json.JSONDecodeError:
            self.output_console.append("Error decoding JSON. Starting with empty data.")
            self.create_initial_data()
            # remove function that cleared the data, now we just populate it with some default crap

        except Exception as e:
            self.output_console.append(f"An error occurred while loading data: {e}")
            self.create_initial_data()

        finally:
            self.update_completer()

    def create_initial_data(self):
        # Create initial data
	    # Define the data to be written to the JSON file
        # just some random crap as example data
	    self.host_data = {
		    "localhost": {
			    "username": "guest",
			    "password": "WjNWbGMzUT0=",
			    "port": "22"
		    },
		    "172.16.1.16": {
			    "username": "dairy",
			    "password": "WjNWbGMzUT0=",
			    "port": "22"
		    }
	    }
        # Save the initial data to the file
        self.save_data()

    def save_data(self):
        # Initialize an empty dictionary to hold the transformed data
        data = {}

        # Iterate over the hostnames and fill in the data dictionary
        for hostname in self.host_data['hostnames']:
            data[hostname] = {
                "username": self.host_data['usernames'].get(hostname, ""),
                "password": self.host_data['passwords'].get(hostname, ""),
                "port": self.host_data['ports'].get(hostname, "22")  # Default to port 22 if not specified
            }
        file_name = "sftp.json"

        # Write the data to a JSON file
        with open(file_name, 'w') as file:
            json.dump(data, file, indent=4)

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
