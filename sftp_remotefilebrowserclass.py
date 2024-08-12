from sftp_filebrowserclass import FileBrowser
from PyQt5.QtWidgets import QTableView, QFileDialog, QMessageBox, QInputDialog, QHeaderView
from PyQt5.QtCore import Qt, QModelIndex
from icecream import ic
import os
import stat

from sftp_remotefiletablemodel import RemoteFileTableModel
from sftp_creds import get_credentials, create_random_integer, set_credentials, create_random_integer
from datetime import datetime
from sftp_downloadworkerclass import create_response_queue, delete_response_queue, add_sftp_job, QueueItem
# from sftp_backgroundthreadwindow import queue_display_append

class RemoteFileBrowser(FileBrowser):
    def __init__(self, title, session_id, parent=None):
        super().__init__(title, session_id, parent)
        self.model = RemoteFileTableModel(self.session_id)
        self.table.setModel(self.model)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        
        # Set column widths
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)

    def refresh_file_list(self):
        self.model.refresh_file_list()

    # Override any file operation methods (like delete, rename, etc.) to call refresh_file_list
    def delete_file(self, filename):
        # Implement your delete logic here
        # ...
        # After successful deletion:
        self.refresh_file_list()

    # Add similar overrides for other file operations
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        
        # Connect double-click event to double_click_handler
        self.table.doubleClicked.connect(self.double_click_handler)
        
        # Refresh the file list
        self.refresh_file_list()

        set_credentials(self.session_id, 'current_remote_directory', self.sftp_getcwd())

    def is_remote_browser(self):
        return True

    def refresh_file_list(self):
        self.model.refresh_file_list()

    def close_sftp_connection(self):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job("", True, "", True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "close", job_id)

        while queue.empty():
            self.non_blocking_sleep(100)
        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"Error closing SFTP connection: {error}")
        else:
            self.message_signal.emit("SFTP connection closed successfully")

        delete_response_queue(job_id)

    def prompt_and_create_directory(self):
        # Prompt the user for a new directory name
        directory_name, ok = QInputDialog.getText(
            None,
            'Create New Directory',
            'Enter the name of the new directory:'
        )

        if ok and directory_name:
            try:
                creds = get_credentials(self.session_id)
                current_remote_directory = creds.get('current_remote_directory', '.')
                new_directory_path = self.get_normalized_remote_path(current_remote_directory, directory_name)
                
                # Attempt to create the directory remotely
                self.sftp_mkdir(new_directory_path)
                self.message_signal.emit(f"'{new_directory_path}' created successfully.")
                self.model.get_files()
                self.notify_observers()
            except Exception as e:
                self.message_signal.emit(f"Error creating directory: {e}")

    def sftp_getcwd(self):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue( job_id )

        try:
            add_sftp_job(creds.get('current_remote_directory'), True, ".", True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "getcwd", job_id)
        except Exception as e:
            print(f"Error in sftp_getcwd: {e}")

        while queue.empty():
            self.non_blocking_sleep(100)  # Sleeps for 100 milliseconds
        response = queue.get_nowait()

        if response == "error":
            response = queue.get_nowait()
            print(f"Error in sftp_getcwd: {response}")
            new_path = None
        else:
            new_path = queue.get_nowait()

        delete_response_queue(job_id)
        return new_path

    def change_directory(self, path ):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue( job_id )
        
        try:
            # Remote file browser
            if path == "..":
                head, tail = self.split_path(creds.get('current_remote_directory'))
                new_path = head
            else:
                # Ensure there's a trailing slash at the end of the input path
                new_path = os.path.join(creds.get('current_remote_directory'),path)

            # sessions are transient but lets make sure the folder exists
            add_sftp_job(new_path.replace("\\", "/"), True, new_path.replace("\\", "/"), True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "chdir", job_id)

            self.progressBar.setRange(0, 0)
            while queue.empty():
                self.non_blocking_sleep(100)  # Sleeps for 1000 milliseconds (1 second)
            response = queue.get_nowait()
            self.progressBar.setRange(0, 100)

            if response == "error":
                response = queue.get_nowait()
                raise response
            else:
                # if success, set our new remote working path to the newly created path path that we path'd pathily'
                set_credentials(self.session_id, 'current_remote_directory', new_path)

            self.message_signal.emit(f"{new_path}")
            self.model.get_files()
            self.notify_observers()
            self.table.viewport().update()
            f = True
        except Exception as e:
            # Emit the message signal
            self.message_signal.emit(f"change_directory() {e}")
            f = False

        finally:
            delete_response_queue(job_id)
            return f

    def double_click_handler(self, index):
        creds = get_credentials(self.session_id)
        try:
            if not index.isValid():
                return False

            # Retrieve the file path from the model
            temp_path = self.model.data(index, Qt.DisplayRole)
            
            # Early return for parent directory navigation
            if temp_path == "..":
                self.change_directory(temp_path)
                return True

            # Determine the full path
            if not self.is_complete_path(temp_path):
                path = self.get_normalized_remote_path(creds.get('current_remote_directory'), temp_path)
            else:
                path = temp_path

            # Check if the path is a directory or a file
            if self.is_remote_directory(path):
                self.change_directory(path)
            elif self.is_remote_file(path):
                local_path = QFileDialog.getSaveFileName(self, "Save File", os.path.basename(temp_path))[0]
                ic(temp_path, local_path)
                if local_path:
                    # Call upload_download to handle download (or upload if it was local)
                    self.upload_download(path, local_path)
                    # Emit a signal or log the download
                    self.message_signal.emit(f"Downloaded file: {path} to {local_path}")
            
            return True

        except Exception as e:
            ic(e)
            return False

    def change_directory_handler(self):
        selected_item, ok = QInputDialog.getText(self, 'Input Dialog', 'Enter directory name:')

        if not ok:
            return

        if self.is_remote_directory(selected_item):
            ic(selected_item)
            self.change_directory(selected_item)

    def remove_trailing_dot(self, s):
        if s.endswith('/.'):
            return s[:-1]  # Remove the last character (dot)
        else:
            return s

    def remove_directory_with_prompt(self, remote_path=None, always=0):
        self.always = always
        creds = get_credentials(self.session_id)
        current_remote_directory = creds.get('current_remote_directory', '.')

        if remote_path is None or remote_path is False:
            current_browser = self.focusWidget()
            if current_browser is not None and isinstance(current_browser, QTableView):
                current_index = current_browser.currentIndex()
                if current_index.isValid():
                    selected_item = current_browser.model().data(current_index, Qt.DisplayRole)
                    if current_remote_directory == '.':
                        current_remote_directory = self.sftp_getcwd()
                    set_credentials(self.session_id, 'current_remote_directory', self.remove_trailing_dot(current_remote_directory))
                    remote_path = self.get_normalized_remote_path(current_remote_directory, selected_item)
                else:
                    self.message_signal.emit("No valid item selected.")
                    return
            else:
                self.message_signal.emit("No valid browser selected.")
                return

        if not remote_path:
            self.message_signal.emit("No valid path provided.")
            return

        try:
            if self.is_remote_file(remote_path):
                self.remove_file(remote_path)
            elif self.is_remote_directory(remote_path):
                self.remove_directory(remote_path)
            else:
                self.message_signal.emit(f"Invalid path: {remote_path}")
        except Exception as e:
            self.message_signal.emit(f"remove_directory_with_prompt() {str(e)}")
        finally:
            try:
                self.refresh_file_list()
            except Exception as refresh_error:
                self.message_signal.emit(f"Error refreshing file list: {str(refresh_error)}")

    def remove_file(self, remote_path):
        full_remote_path = self.get_normalized_remote_path(remote_path)
        
        if not self.always:
            response = QMessageBox.question(
                None,
                'Confirmation',
                f"Are you sure you want to remove the file '{full_remote_path}'?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll,
                QMessageBox.No
            )
            if response == QMessageBox.YesToAll:
                self.always = 1
            elif response == QMessageBox.No:
                return

        self.sftp_remove(full_remote_path)
        self.message_signal.emit(f"File '{full_remote_path}' removed successfully.")

    def remove_directory(self, remote_path):
        directory_contents_attr = self.sftp_listdir_attr(remote_path)

        subdirectories = [entry for entry in directory_contents_attr if stat.S_ISDIR(entry.st_mode)]
        files = [entry for entry in directory_contents_attr if stat.S_ISREG(entry.st_mode)]

        if not self.always and (subdirectories or files):
            response = QMessageBox.question(
                None,
                'Confirmation',
                f"The directory '{remote_path}' contains subdirectories or files. Do you want to remove them all?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll,
                QMessageBox.No
            )

            if response == QMessageBox.YesToAll:
                self.always = 1
            elif response == QMessageBox.No:
                return

        # Remove files
        for entry in files:
            entry_path = os.path.join(remote_path, entry.filename)
            self.message_signal.emit(f"Removing file: {entry_path}")
            self.sftp_remove(entry_path)

        # Recursively remove subdirectories
        for entry in subdirectories:
            entry_path = os.path.join(remote_path, entry.filename)
            self.message_signal.emit(f"Recursing into subdirectory: {entry_path}")
            self.remove_directory_with_prompt(entry_path, self.always)

        # Remove the directory
        self.sftp_rmdir(remote_path)
        self.message_signal.emit(f"Directory '{remote_path}' removed successfully.")

    def sftp_remove(self, remote_path):
        if not remote_path or remote_path.strip() == '':
            self.message_signal.emit("Error: No valid path provided for removal.")
            return

        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        try:
            # Ensure the remote_path is normalized
            normalized_path = self.get_normalized_remote_path(remote_path)
            self.message_signal.emit(f"Attempting to remove: {normalized_path}")

            # Check if the file or directory exists before attempting to remove it
            if not self.is_remote_file(normalized_path) and not self.is_remote_directory(normalized_path):
                raise FileNotFoundError(f"No such file or directory: {normalized_path}")

            # Determine if it's a file or directory
            if self.is_remote_file(normalized_path):
                operation = "remove"
                self.message_signal.emit(f"Removing file: {normalized_path}")
            elif self.is_remote_directory(normalized_path):
                operation = "rmdir"
                self.message_signal.emit(f"Removing directory: {normalized_path}")
            else:
                raise ValueError(f"Unknown file type for {normalized_path}")

            add_sftp_job(normalized_path, True, "", False, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), operation, job_id)

            while queue.empty():
                self.non_blocking_sleep(100)
            response = queue.get_nowait()

            if response == "error":
                error = queue.get_nowait()
                if "No such file" in str(error):
                    self.message_signal.emit(f"'{normalized_path}' does not exist or has already been removed.")
                else:
                    self.message_signal.emit(f"Error removing '{normalized_path}': {error}")
            else:
                self.message_signal.emit(f"'{normalized_path}' removed successfully.")
            
            # Refresh the file list after removal
            self.refresh_file_list()
        except FileNotFoundError as e:
            self.message_signal.emit(str(e))
        except Exception as e:
            self.message_signal.emit(f"Exception in sftp_remove: {str(e)}")
        finally:
            try:
                delete_response_queue(job_id)
            except Exception as delete_error:
                self.message_signal.emit(f"Error deleting response queue: {str(delete_error)}")

    def upload_download(self, optionalpath=None):
        creds = get_credentials(self.session_id)
        
        if creds.get('current_remote_directory') == '.':
            current_remote_directory = self.sftp_getcwd()
            set_credentials(self.session_id, 'current_remote_directory', current_remote_directory)
            creds = get_credentials(self.session_id)
        else:
            current_remote_directory = creds.get('current_remote_directory')

        current_browser = self.focusWidget()

        if current_browser is not None and isinstance(current_browser, QTableView):
            indexes = current_browser.selectedIndexes()
            has_valid_item = False  # Track if we found any valid items
            
            for index in indexes:
                selected_item_text = ""

                if isinstance(index, QModelIndex):
                    if index.isValid():
                        selected_item_text = current_browser.model().data(index, Qt.DisplayRole)
                elif isinstance(index, str):
                    selected_item_text = index

                if optionalpath:
                    selected_item_text = optionalpath

                if selected_item_text:
                    try:
                        if optionalpath == None:
                            remote_entry_path = self.get_normalized_remote_path(current_remote_directory, selected_item_text)
                        else:
                            remote_entry_path = self.get_normalized_remote_path(selected_item_text)

                        local_base_path = creds.get('current_local_directory')
                        local_entry_path = os.path.join(local_base_path, os.path.basename(remote_entry_path))

                        # Ensure the local directory exists
                        os.makedirs(local_base_path, exist_ok=True)

                        if self.is_remote_directory(remote_entry_path):
                            self.download_directory(remote_entry_path, local_base_path)
                        else:
                            job_id = create_random_integer()
                            queue_item = QueueItem(os.path.basename(remote_entry_path), job_id)
                            add_sftp_job(remote_entry_path, True, local_entry_path, False, 
                                        self.init_hostname, self.init_username, 
                                        self.init_password, self.init_port, 
                                        "download", job_id)
                            
                            # Wait for the download to complete
                            queue = create_response_queue(job_id)
                            while queue.empty():
                                self.non_blocking_sleep(100)
                            response = queue.get_nowait()

                            if response == "error":
                                error = queue.get_nowait()
                                self.message_signal.emit(f"Error downloading {remote_entry_path}: {error}")
                            else:
                                self.message_signal.emit(f"Successfully downloaded: {remote_entry_path} to {local_entry_path}")
                            
                            delete_response_queue(job_id)

                        ic(f"Downloading: {remote_entry_path} to {local_entry_path}")
                        has_valid_item = True  # Mark as valid item found
                    except Exception as e:
                        error_message = f"upload_download() encountered an error: {str(e)}"
                        self.message_signal.emit(error_message)
                        ic(e)
                else:
                    self.message_signal.emit("No valid path provided.")
            
            if not has_valid_item:
                self.message_signal.emit("No valid items selected.")
        else:
            self.message_signal.emit("Current browser is not a valid QTableView.")

    def download_directory(self, source_directory, destination_directory, always=0):
        self.always = always

        try:
            # Create a local folder with the same name as the remote folder
            local_folder = os.path.join(destination_directory, os.path.basename(source_directory))

            if os.path.exists(local_folder):
                # Check if 'always' option was selected before
                
                # If not, show the dialog with 'always' option
                ic(self.always)
                if not self.always:
                    response = QMessageBox.question(
                        self,
                        'Folder Exists',
                        f"The folder '{local_folder}' already exists. Do you want to proceed?",
                        QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll,
                        QMessageBox.No
                    )

                    if response == QMessageBox.YesToAll:
                        self.always = 1

                    elif response == QMessageBox.No:
                        self.always = 0
                        return
            else:
                self.message_signal.emit(f"mkdir {local_folder}")
                os.makedirs(local_folder, exist_ok=True)
                # creating a local directory, let local browser know to update its contents
                # self.notify_observers()

            # List the contents of the remote directory
            directory_contents = self.sftp_listdir(source_directory)
            # ic(directory_contents)

            # Download files and recurse into subdirectories
            for entry in directory_contents:
                # entry_path = os.path.join(source_directory, entry)
                entry_path = self.get_normalized_remote_path( source_directory, entry)
                ic(entry_path)
                local_entry_path = os.path.join(local_folder, entry)

                # If it's a directory, recursively download its contents
                # ic()
                ic(local_entry_path)
                if self.is_remote_directory(entry_path):
                    self.message_signal.emit(f"download_directory() {entry_path}, {local_folder}")
                    self.download_directory(entry_path, local_folder, self.always)
                    # local directory view needs to be updated with downloaded folder
                    # self.notify_observers()
                else:
                    # If it's a file, download it
                    self.message_signal.emit(f"download_directory() {entry_path}, {local_entry_path}")

                    if os.path.exists(local_entry_path):
                        # changed indent here after noting the 'pass' statement above... 
                        if not self.always:
                            response = QMessageBox.question(
                            self,
                            'Folder Exists',
                            f"The folder '{local_folder}' already exists. Do you want to proceed?",
                            QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll,
                            QMessageBox.No
                            )
    
                            if response == QMessageBox.YesToAll:
                                self.always = 1
                            elif response == QMessageBox.No:
                                return
                   
                    try:
                        os.remove(local_entry_path)
                        # local directory view needs to be updated with removed folder
                    except Exception as e:
                        pass

                    self.message_signal.emit(f"download_directory() {entry_path}, {local_entry_path}")
                    job_id = create_random_integer()

                    queue_item = QueueItem( os.path.basename(entry_path), job_id )
                    # ic()
                    add_sftp_job(entry_path, True, local_entry_path, False, self.init_hostname, self.init_username, self.init_password, self.init_port, "download", job_id)

        except Exception as e:
            self.message_signal.emit(f"download_directory() {e}")
            ic(e)

        finally:
            self.notify_observers()
