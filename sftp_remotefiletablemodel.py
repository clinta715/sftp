from PyQt5.QtCore import QVariant, QAbstractTableModel, QModelIndex, QTimer, QDateTime, Qt, QEventLoop
import base64
import queue
import time
from icecream import ic
from PyQt5.QtGui import QFont, QColor
from sftp_creds import get_credentials, create_random_integer
from sftp_downloadworkerclass import create_response_queue, delete_response_queue, add_sftp_job
import stat  # Import stat for file type checking

class RemoteFileTableModel(QAbstractTableModel):
    def __init__(self, session_id, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.file_list = []  # Initialize as an empty list
        self.column_names = ['Name', 'Size', 'Permissions', 'Modified']
        self.cache = {}  # Add a cache for directory listings
        self.cache_time = {}  # Track when each directory was last updated
        self.cache_duration = 60  # Cache duration in seconds

    def is_remote_browser(self):
        return True

    def rowCount(self, parent=QModelIndex()):
        return len(self.file_list)

    def columnCount(self, parent=QModelIndex()):
        return len(self.column_names)

    def invalidate_cache(self, directory=None):
        if directory:
            self.cache.pop(directory, None)
            self.cache_time.pop(directory, None)
        else:
            self.cache.clear()
            self.cache_time.clear()

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.file_list)):
            return QVariant()

        try:
            file = self.file_list[index.row()]
        except Exception as e:
            return QVariant()

        column = index.column()
        is_directory = stat.S_ISDIR(file[2])  # Use stat.S_ISDIR to check if it's a directory

        if role == Qt.DisplayRole:
            if column == 0:
                if is_directory:
                    return f"📁 {file[0]}"  # Add folder icon for directories
                else:
                    return f"📄 {file[0]}"  # Add document icon for files
            elif column == 1:
                return str(file[1])  # size
            elif column == 2:
                return oct(file[2])[-4:]  # permissions as a string
            elif column == 3:
                return file[3]  # modified_date

        if role == Qt.FontRole:
            font = QFont()
            if is_directory:
                font.setBold(True)
            return font

        if role == Qt.ForegroundRole:
            if is_directory:
                return QColor(Qt.blue)
            else:
                return QColor(Qt.darkGray)

        return QVariant()

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.column_names[section]
        return QVariant()

    def sort(self, column, order):
        self.layoutAboutToBeChanged.emit()

        if column == 0:
            try:
                self.file_list.sort(key=lambda x: x[0], reverse=(order == Qt.DescendingOrder))
            except Exception as e:
                pass
        elif column == 1:
            try:
                self.file_list.sort(key=lambda x: x[1], reverse=(order == Qt.DescendingOrder))
            except Exception as e:
                pass
        elif column == 2:
            try:
                self.file_list.sort(key=lambda x: x[2], reverse=(order == Qt.DescendingOrder))
            except Exception as e:
                pass
        elif column == 3:
            try:
                self.file_list.sort(key=lambda x: x[3], reverse=(order == Qt.DescendingOrder))
            except Exception as e:
                pass

        self.layoutChanged.emit()

    def get_files(self, force_refresh=False):
        creds = get_credentials(self.session_id)
        current_dir = creds.get('current_remote_directory', '.')

        if not force_refresh and current_dir in self.cache and time.time() - self.cache_time.get(current_dir, 0) < self.cache_duration:
            if self.file_list == self.cache[current_dir]:
                return
            self.file_list = self.cache[current_dir]
            self.layoutChanged.emit()
            return

        items = self.sftp_listdir_attr(current_dir)
        
        self.beginResetModel()
        new_file_list = [("..", 0, 0, "----", "----")]  # Corrected the tuple structure

        for item in items:
            try:
                name = item.filename
                size = item.st_size
                permissions = item.st_mode  # Store st_mode as an integer
                modified_time = QDateTime.fromSecsSinceEpoch(item.st_mtime).toString(Qt.ISODate)
                new_file_list.append((name, size, permissions, modified_time))
            except Exception as e:
                ic(f"Error processing file {item.filename if hasattr(item, 'filename') else 'unknown'}: {str(e)}")

        self.file_list = new_file_list
        self.cache[current_dir] = self.file_list
        self.cache_time[current_dir] = time.time()
        self.endResetModel()
        self.layoutChanged.emit()

    def non_blocking_sleep(self, ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec_()

    def sftp_listdir_attr(self, remote_path):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        try:
            add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "listdir_attr", job_id)
        except Exception as e:
            ic(e)

        while queue.empty():
            self.non_blocking_sleep(100)

        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            diag = f"RemoteFileTableModel sftp_listdir_attr() {error}"
            f = False
        else:
            list = queue.get_nowait()
            f = True

        delete_response_queue(job_id)
        if f:
            return list
        else:
            return f

    def invalidate_cache(self, directory=None):
        if directory:
            self.cache.pop(directory, None)
            self.cache_time.pop(directory, None)
        else:
            self.cache.clear()
            self.cache_time.clear()
