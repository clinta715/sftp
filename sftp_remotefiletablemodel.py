from PyQt5.QtCore import QVariant,QAbstractTableModel,QModelIndex,QTimer, QDateTime, Qt, QEventLoop
import base64
import queue
from icecream import ic

from sftp_creds import get_credentials, create_random_integer
from sftp_downloadworkerclass import create_response_queue, delete_response_queue, add_sftp_job

class RemoteFileTableModel(QAbstractTableModel):
    def __init__(self, session_id, parent=None):
        super().__init__(parent)  # Simplified form in Python 3
        self.session_id = session_id
        self.file_list = []  # Initialize as an empty list
        self.column_names = ['Name', 'Size', 'Permissions', 'Modified']
        # ic("remote file table model init")
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

        # ic("Emitting layoutchanged")
        self.layoutChanged.emit()

    def get_files(self):
        ic()
        # ic("remote file table model get files")
        creds = get_credentials(self.session_id)
        # ic(creds)
        """
        Fetches file attributes from the specified path using the given SFTP connection.
        :param sftp: Paramiko SFTP client object
        :param path: Path to the directory on the remote server
        """
        # List all files and directories in the specified path
        items = self.sftp_listdir_attr(creds.get('current_remote_directory'))
        # ic(items)
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
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue( job_id )

        ic()
        ic(remote_path)
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
        ic()
        if f:
            return list
        else:
            return f
