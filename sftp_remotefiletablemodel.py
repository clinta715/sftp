from PyQt5.QtCore import QVariant,QAbstractTableModel,QModelIndex,QTimer, QDateTime, Qt, QEventLoop
import base64
import queue
import logging
from icecream import ic

from sftp_creds import get_credentials, create_random_integer
from sftp_downloadworkerclass import create_response_queue, delete_response_queue, add_sftp_job

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class RemoteFileTableModel(QAbstractTableModel):
    def __init__(self, session_id, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.file_list = []
        self.column_names = ['Name', 'Size', 'Permissions', 'Modified']
        self.cache = {}  # Add a cache dictionary
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
        creds = get_credentials(self.session_id)
        sftp = creds.get('sftp')
        if sftp:
            try:
                remote_path = creds.get('current_remote_directory', '.')
                self.file_list = sftp.listdir_attr(remote_path)
                self.layoutChanged.emit()
            except Exception as e:
                print(f"Error refreshing file list: {str(e)}")

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.file_list)):
            return None

        file_attr = self.file_list[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            if column == 0:  # Name
                return file_attr.filename
            elif column == 1:  # Size
                return str(file_attr.st_size)
            elif column == 2:  # Permissions
                return oct(file_attr.st_mode)[-3:]
            elif column == 3:  # Modified
                return str(datetime.fromtimestamp(file_attr.st_mtime))

        return None
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

        # ic("Emitting layoutchanged")
        self.layoutChanged.emit()

    def get_files(self):
        logger.debug("Entering get_files method")
        creds = get_credentials(self.session_id)
        current_remote_directory = creds.get('current_remote_directory', '.')
        logger.debug(f"Current remote directory: {current_remote_directory}")

        self.beginResetModel()
        self.file_list.clear()

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
        
        except Exception as e:
            logger.error(f"Error fetching remote files: {str(e)}")
            # You might want to emit a signal here to inform the user about the error

        logger.debug(f"Total files in file_list: {len(self.file_list)}")
        self.endResetModel()
        self.layoutChanged.emit()
        logger.debug("Exiting get_files method")

    def non_blocking_sleep(self, ms):
        # sleep function that shouldn't block any other threads
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec_()

    def sftp_listdir_attr(self, remote_path):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue( job_id )

        # the slashes/backslashes stuff is an attempt at windows compatibility
        try:
            add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "listdir_attr", job_id )
        except Exception as e:
            ic(e)

        while queue.empty():
            self.non_blocking_sleep(100)  # Sleeps for 1000 milliseconds (1 second)

        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            diag = f"RemoteFileTableModel sftp_listdir_attr() {error}"
            # always 2 responses on stack, if its an error, get message
            f = False
        else:
            # if its not an error its a success and heres the list
            list = queue.get_nowait()
            f = True

        delete_response_queue(job_id)
        if f:
            return list
        else:
            return f

