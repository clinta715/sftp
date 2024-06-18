from PyQt5.QtCore import QVariant,QAbstractTableModel,QModelIndex,Qt

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