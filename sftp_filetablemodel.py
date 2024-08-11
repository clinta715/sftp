from PyQt5.QtCore import QVariant,QAbstractTableModel,QModelIndex,Qt
from pathlib import Path
import os
import datetime
from icecream import ic

from sftp_remotefiletablemodel import RemoteFileTableModel
from sftp_creds import get_credentials, set_credentials

class FileTableModel(QAbstractTableModel):
    def __init__(self, session_id):
        super().__init__()
        self.file_list = []
        self.session_id = session_id
        ic("Initializing FileTableModel")
        
        creds = get_credentials(self.session_id)
        current_dir = creds.get('current_local_directory')
        
        if not current_dir or not os.path.exists(current_dir):
            current_dir = os.getcwd()
            ic(f"Setting current directory to: {current_dir}")
        
        set_credentials(self.session_id, 'current_local_directory', current_dir)
        self.directory = Path(current_dir)
        ic(f"Initial directory set to: {self.directory}")
        
        self.column_names = ['Name', 'Size', 'Permissions', 'Modified']
        self.get_files()

    def is_remote_browser(self):
        # dummy function in local-files portion of code
        return False

    def get_files(self):
        ic("Getting local files")
        creds = get_credentials(self.session_id)

        self.directory = Path(creds.get('current_local_directory'))
        ic(f"Current directory: {self.directory}")

        self.beginResetModel()
        self.file_list = []  # Clear the list completely

        # Add the '..' entry to represent the parent directory
        self.file_list.append(["..", 0, "----", "----"])

        try:
            items = list(self.directory.iterdir())
            ic(f"Found {len(items)} items in directory")
            for item in items:
                name = item.name
                size = item.stat().st_size
                permissions = oct(item.stat().st_mode)[-4:]
                modified_time = datetime.datetime.fromtimestamp(item.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                self.file_list.append([name, size, permissions, modified_time])
                ic(f"Added item: {name}")

            # Sort the file list by name, ignoring case
            self.file_list[1:] = sorted(self.file_list[1:], key=lambda x: x[0].lower())
        except Exception as e:
            ic(f"Error getting files: {str(e)}")

        ic(f"Total items in file_list: {len(self.file_list)}")
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
