from sftp_browserclass import Browser
from sftp_filetablemodel import FileTableModel
from PyQt5.QtWidgets import QMessageBox, QHeaderView
from PyQt5.QtCore import Qt
import os 
import shutil
from icecream import ic

from sftp_creds import get_credentials

class FileBrowser(Browser):
    def __init__(self, title, session_id, parent=None):
        super().__init__(title, session_id, parent)  # Initialize the FileBrowser parent class
        # ic("init file browser class object")
        try:
            self.model = FileTableModel(session_id)
        except Exception as e:
            ic(e)

        self.table.setModel(self.model)

        # Set horizontal scroll bar policy for the entire table
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # Resize the first column based on its contents
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        # ic("file browser init completed")

    def remove_directory_with_prompt(self, local_path=None, always=0):
        self.always = always
        creds = get_credentials( self.session_id )
        
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
                        local_path = os.path.join( creds.get('current_local_directory'), selected_item )
                        # ic(local_path)
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

            if subdirectories or files and not self.always:
                # Directory has child items, prompt for confirmation using QMessageBox
                response = QMessageBox.question(
                    None,
                    'Confirmation',
                    f"The directory '{local_path}' contains subdirectories or files. Do you want to remove them all?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll,
                    QMessageBox.No
                )

                if response == QMessageBox.YesToAll:
                    self.always = 1

                if response == QMessageBox.No:
                    return

                # Recursively remove subdirectories
                for entry in subdirectories:
                    entry_path = os.path.join(local_path, entry)
                    self.remove_directory_with_prompt(entry_path, self.always)

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
