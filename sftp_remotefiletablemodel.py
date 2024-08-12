from PyQt5.QtCore import QVariant, QAbstractTableModel, QModelIndex, QTimer, QDateTime, Qt, QEventLoop
from PyQt5.QtGui import QFont
import base64
import queue
import logging
import time
from icecream import ic
from datetime import datetime
from functools import wraps

from sftp_creds import get_credentials, create_random_integer
from sftp_downloadworkerclass import create_response_queue, delete_response_queue, add_sftp_job

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def debounce(wait):
    def decorator(fn):
        timer = None
        @wraps(fn)
        def debounced(*args, **kwargs):
            nonlocal timer
            if timer is not None:
                timer.stop()
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: fn(*args, **kwargs))
            timer.start(wait)
        return debounced
    return decorator

class RemoteFileTableModel(QAbstractTableModel):
    def __init__(self, session_id, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.file_list = []
        self.column_names = ['Name', 'Size', 'Permissions', 'Modified']
        self.cache = {}
        self.cache_timestamp = {}
        self.cache_duration = 30  # Cache valid for 30 seconds
        logger.debug(f"Initializing RemoteFileTableModel with session_id: {session_id}")
        self.get_files()  # Call get_files once when initializing

    def is_remote_browser(self):
        return True

    def rowCount(self, parent=QModelIndex()):
        # Return the number of files
        return len(self.file_list)

    def columnCount(self, parent=QModelIndex()):
        # Return the number of columns
        return len(self.column_names)

    def refresh_file_list(self):
        self.get_files()  # Call get_files to completely refresh the file list


    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.file_list)):
            return None

        file_attr = self.file_list[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            if isinstance(file_attr, tuple):
                # Handle tuple case
                if column == 0:  # Name
                    return file_attr[0]
                elif column == 1:  # Size
                    return str(file_attr[1])
                elif column == 2:  # Permissions
                    return file_attr[2]
                elif column == 3:  # Modified
                    return file_attr[3]
            else:
                # Handle object case
                if column == 0:  # Name
                    return getattr(file_attr, 'filename', '')
                elif column == 1:  # Size
                    return str(getattr(file_attr, 'st_size', 0))
                elif column == 2:  # Permissions
                    return oct(getattr(file_attr, 'st_mode', 0))[-3:]
                elif column == 3:  # Modified
                    return str(datetime.fromtimestamp(getattr(file_attr, 'st_mtime', 0)))
        
        elif role == Qt.ForegroundRole:
            # Check if it's a directory
            if isinstance(file_attr, tuple):
                name = file_attr[0]
                is_dir = name == ".." or file_attr[2].startswith('d')
            else:
                name = getattr(file_attr, 'filename', '')
                is_dir = name == ".." or (getattr(file_attr, 'st_mode', 0) & 0o40000)
            
            if is_dir:
                return QVariant(Qt.blue)  # Return blue color for directories
        
        elif role == Qt.FontRole:
            # Check if it's a directory
            if isinstance(file_attr, tuple):
                name = file_attr[0]
                is_dir = name == ".." or file_attr[2].startswith('d')
            else:
                name = getattr(file_attr, 'filename', '')
                is_dir = name == ".." or (getattr(file_attr, 'st_mode', 0) & 0o40000)
            
            if is_dir:
                font = QFont()
                font.setBold(True)
                return QVariant(font)  # Return bold font for directories

        return None

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

        # ic("Emitting layoutchanged")
        self.layoutChanged.emit()

    def get_files(self):
        logger.debug("Entering get_files method")
        creds = get_credentials(self.session_id)
        current_remote_directory = creds.get('current_remote_directory', '.')
        logger.debug(f"Current remote directory: {current_remote_directory}")

        # Check if cache is valid
        if current_remote_directory in self.cache and time.time() - self.cache_timestamp.get(current_remote_directory, 0) < self.cache_duration:
            logger.debug("Using cached file list")
            self.file_list = self.cache[current_remote_directory]
        else:
            self.refresh_file_list()

        return self.file_list

    @debounce(300)  # 300 ms debounce
    def refresh_file_list(self):
        logger.debug("Refreshing file list")
        creds = get_credentials(self.session_id)
        current_remote_directory = creds.get('current_remote_directory', '.')

        self.beginResetModel()
        self.file_list = []  # Clear the list completely

        # Always add the '..' entry
        self.file_list.append(("..", 0, "----", "----"))
        logger.debug("Added '..' entry to file_list")

        try:
            logger.debug("Attempting to fetch remote files")
            items = self.sftp_listdir_attr(current_remote_directory)
            logger.debug(f"Fetched {len(items)} items from remote directory")
            
            for item in items:
                name = getattr(item, 'filename', '')
                size = getattr(item, 'st_size', 0)
                permissions = oct(getattr(item, 'st_mode', 0))[-4:]
                modified_time = QDateTime.fromSecsSinceEpoch(getattr(item, 'st_mtime', 0)).toString(Qt.ISODate)
                
                self.file_list.append((name, size, permissions, modified_time))
                logger.debug(f"Added file to list: {name}")
        
            # Sort the file list by name, ignoring case
            self.file_list[1:] = sorted(self.file_list[1:], key=lambda x: x[0].lower())

            # Update cache
            self.cache[current_remote_directory] = self.file_list
            self.cache_timestamp[current_remote_directory] = time.time()

        except Exception as e:
            logger.error(f"Error fetching remote files: {str(e)}")
            # You might want to emit a signal here to inform the user about the error

        logger.debug(f"Total files in file_list: {len(self.file_list)}")
        self.endResetModel()
        self.layoutChanged.emit()
        logger.debug("Exiting refresh_file_list method")

    def get_files(self):
        logger.debug("Entering get_files method")
        creds = get_credentials(self.session_id)
        current_remote_directory = creds.get('current_remote_directory', '.')
        logger.debug(f"Current remote directory: {current_remote_directory}")

        # Check if cache is valid
        if current_remote_directory in self.cache and time.time() - self.cache_timestamp.get(current_remote_directory, 0) < self.cache_duration:
            logger.debug("Using cached file list")
            self.file_list = self.cache[current_remote_directory]
        else:
            self.refresh_file_list()

        return self.file_list

    def non_blocking_sleep(self, ms):
        # sleep function that shouldn't block any other threads
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec_()

    def sftp_listdir_attr(self, remote_path):
        if remote_path in self.cache and time.time() - self.cache_timestamp.get(remote_path, 0) < self.cache_duration:
            logger.debug(f"Using cached listdir_attr for {remote_path}")
            return self.cache[remote_path]

        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue( job_id )

        # the slashes/backslashes stuff is an attempt at windows compatibility
        try:
            add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "listdir_attr", job_id )
        except Exception as e:
            ic(e)

        while queue.empty():
            self.non_blocking_sleep(100)  # Sleeps for 100 milliseconds

        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            logger.error(f"RemoteFileTableModel sftp_listdir_attr() {error}")
            return []
        else:
            list_result = queue.get_nowait()
            self.cache[remote_path] = list_result
            self.cache_timestamp[remote_path] = time.time()

        delete_response_queue(job_id)
        return list_result

