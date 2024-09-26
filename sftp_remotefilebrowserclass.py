from sftp_filebrowserclass import FileBrowser
from PyQt5.QtWidgets import QTableView, QFileDialog, QMessageBox, QInputDialog, QHeaderView
from PyQt5.QtCore import Qt, QModelIndex
from icecream import ic
import os
import stat
import time

from sftp_remotefiletablemodel import RemoteFileTableModel
from sftp_creds import get_credentials, create_random_integer, set_credentials, create_random_integer
from sftp_downloadworkerclass import create_response_queue, delete_response_queue, add_sftp_job, QueueItem
# from sftp_backgroundthreadwindow import queue_display_append

class RemoteFileBrowser(FileBrowser):
    def prompt_overwrite(self, item_path):
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Question)
        msg_box.setText(f"The item '{item_path}' already exists.")
        msg_box.setInformativeText("What would you like to do?")
        msg_box.setWindowTitle("Overwrite Confirmation")

        cancel_btn = msg_box.addButton("Cancel All", QMessageBox.RejectRole)
        skip_btn = msg_box.addButton("Skip", QMessageBox.NoRole)
        skip_all_btn = msg_box.addButton("Skip All", QMessageBox.NoRole)
        overwrite_btn = msg_box.addButton("Overwrite", QMessageBox.YesRole)
        overwrite_all_btn = msg_box.addButton("Overwrite All", QMessageBox.YesRole)

        msg_box.exec_()

        if msg_box.clickedButton() == cancel_btn:
            return "cancel"
        elif msg_box.clickedButton() == skip_btn:
            return "skip"
        elif msg_box.clickedButton() == skip_all_btn:
            return "skip_all"
        elif msg_box.clickedButton() == overwrite_btn:
            return "overwrite"
        elif msg_box.clickedButton() == overwrite_all_btn:
            return "overwrite_all"
    def __init__(self, title, session_id, parent=None):
        super().__init__(title, session_id, parent)  # Initialize the FileBrowser parent class
        self.model = RemoteFileTableModel(self.session_id)

        self.table.setModel(self.model)
        # Set horizontal scroll bar policy for the entire table
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # Make all columns resizable
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        set_credentials(self.session_id, 'current_remote_directory', self.sftp_getcwd())

        # Add these lines to enable full row selection
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)

        # Initialize the model immediately
        self.initialize_model()

    def initialize_model(self):
        creds = get_credentials(self.session_id)
        current_dir = creds.get('current_remote_directory', '.')
        if not self.model.file_list:
            self.model.get_files()
        self.change_directory(current_dir, force_refresh=False)
        self.table.resizeColumnsToContents()

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
                self.model.invalidate_cache()
                self.model.get_files(force_refresh=True)
                self.notify_observers()
            except Exception as e:
                self.message_signal.emit(f"Error creating directory: {e}")

    def sftp_getcwd(self):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue( job_id )

        ic()
        ic(creds)

        try:
            add_sftp_job(creds.get('current_remote_directory'), True, ".", True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "getcwd", job_id)
        except Exception as e:
            ic(e)

        while queue.empty():
            self.non_blocking_sleep(100)  # Sleeps for 1000 milliseconds (1 second)
        response = queue.get_nowait()

        if response == "error":
            response = queue.get_nowait()
            ic(response)
            new_path = None
        else:
            # if success, set our new remote working path to the newly created path path that we path'd pathily'
            new_path = queue.get_nowait()

        delete_response_queue(job_id)
        ic(new_path)
        return new_path

    def change_directory(self, path, force_refresh=True):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)
        
        try:
            if path == "..":
                head, tail = self.split_path(creds.get('current_remote_directory'))
                new_path = head
            else:
                new_path = os.path.join(creds.get('current_remote_directory'), path)

            # Check if the new path is in the cache and force_refresh is False
            if not force_refresh and new_path in self.model.cache and time.time() - self.model.cache_time.get(new_path, 0) < self.model.cache_duration:
                set_credentials(self.session_id, 'current_remote_directory', new_path)
                self.model.file_list = self.model.cache[new_path]
                self.model.layoutChanged.emit()
                self.message_signal.emit(f"{new_path}")
                self.notify_observers()
                self.table.viewport().update()
                return True

            # If not in cache or force_refresh is True, proceed with SFTP operation
            add_sftp_job(new_path.replace("\\", "/"), True, new_path.replace("\\", "/"), True, 
                         creds.get('hostname'), creds.get('username'), creds.get('password'), 
                         creds.get('port'), "chdir", job_id)

            self.progressBar.setRange(0, 0)
            while queue.empty():
                self.non_blocking_sleep(100)
            response = queue.get_nowait()
            self.progressBar.setRange(0, 100)

            if response == "error":
                raise queue.get_nowait()

            set_credentials(self.session_id, 'current_remote_directory', new_path)
            self.message_signal.emit(f"{new_path}")
            self.model.invalidate_cache()
            self.model.get_files(force_refresh=True)
            self.notify_observers()
            self.table.viewport().update()
            return True

        except Exception as e:
            self.message_signal.emit(f"change_directory() {e}")
            return False

        finally:
            delete_response_queue(job_id)

    def double_click_handler(self, index):
        creds = get_credentials(self.session_id)
        try:
            if not index.isValid():
                return False

            # Always get the data from the first column (filename)
            filename_index = self.model.index(index.row(), 0)
            temp_path = self.model.data(filename_index, Qt.DisplayRole)
            temp_path = temp_path.split(' ', 1)[-1]  # Remove the icon prefix
            
            # Early return for parent directory navigation
            if temp_path == "..":
                ic()
                self.change_directory(temp_path)
                return True

            # Determine the full path
            if not self.is_complete_path(temp_path):
                path = self.get_normalized_remote_path(creds.get('current_remote_directory'), temp_path)
            else:
                path = temp_path
            
            ic(path)

            # Check if the path is a directory or a file
            if self.is_remote_directory(path):
                self.change_directory(path)
            elif self.is_remote_file(path):
                local_path = QFileDialog.getSaveFileName(self, "Save File", os.path.basename(temp_path))[0]
                ic(temp_path, local_path)
                if local_path:
                    # Call upload_download to handle download (or upload if it was local)
                    ic()
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

        ic()
        ic(selected_item)

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

        if remote_path is None or remote_path is False:
            current_browser = self.focusWidget()
            if current_browser is not None:
                current_index = current_browser.currentIndex()
                if current_index.isValid():
                    # Assuming the first column holds the item text you need
                    selected_item = current_browser.model().data(current_index, Qt.DisplayRole)
                    selected_item = selected_item.split(' ', 1)[-1]  # Remove the icon prefix
                    if creds.get('current_remote_directory') == '.':
                        temp_path = self.sftp_getcwd()
                    else:
                        temp_path = creds.get('current_remote_directory')
                    set_credentials(self.session_id, 'current_remote_directory', self.remove_trailing_dot(temp_path))
                    remote_path = os.path.join(creds.get('current_remote_directory'), selected_item)
            else:
                return

        try:
            # Check if the remote path exists
            if not self.sftp_exists(remote_path):
                self.message_signal.emit(f"Remote path '{remote_path}' does not exist.")
                return

            # Check if it's a file
            if self.is_remote_file(remote_path):
                self.sftp_remove(remote_path)
                self.message_signal.emit(f"File '{remote_path}' removed successfully.")
                return

            # Get attributes of directory contents
            directory_contents_attr = self.sftp_listdir_attr(remote_path)

            if directory_contents_attr is False:
                self.message_signal.emit(f"Failed to get contents of '{remote_path}'. It might be an empty directory.")
                # Try to remove the directory even if it's empty
                self.sftp_rmdir(remote_path)
                self.message_signal.emit(f"Empty directory '{remote_path}' removed successfully.")
                return

            # Separate files and subdirectories
            subdirectories = [entry for entry in directory_contents_attr if stat.S_ISDIR(entry.st_mode)]
            files = [entry for entry in directory_contents_attr if stat.S_ISREG(entry.st_mode)]

            if (subdirectories or files) and not self.always:
                response = QMessageBox.question(
                    None,
                    'Confirmation',
                    f"The directory '{remote_path}' contains subdirectories or files. Do you want to remove them all?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll,
                    QMessageBox.No
                )

                if response == QMessageBox.YesToAll:
                    self.always = 1

                if response == QMessageBox.No:
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

        except Exception as e:
            self.message_signal.emit(f"remove_directory_with_prompt() {e}")

        finally:
            self.model.invalidate_cache()
            self.model.get_files(force_refresh=True)

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
            
            skip_all = False
            overwrite_all = False

            for index in indexes:
                # Always get the data from the first column (filename)
                filename_index = self.model.index(index.row(), 0)
                selected_item_text = self.model.data(filename_index, Qt.DisplayRole)
                selected_item_text = selected_item_text.split(' ', 1)[-1]  # Remove the icon prefix

                if optionalpath:
                    selected_item_text = optionalpath

                if selected_item_text:
                    try:
                        if optionalpath == None:
                            remote_entry_path = self.get_normalized_remote_path(current_remote_directory, selected_item_text)
                        else:
                            remote_entry_path = self.get_normalized_remote_path(selected_item_text)

                        local_base_path = creds.get('current_local_directory')
                        local_entry_path = os.path.join(local_base_path, selected_item_text)

                        ic(selected_item_text)
                        ic(remote_entry_path)
                        ic(local_base_path)
                        ic(local_entry_path)

                        if self.is_remote_directory(remote_entry_path):
                            ic(remote_entry_path)
                            if not skip_all and not overwrite_all and os.path.exists(local_entry_path):
                                action = self.prompt_overwrite(local_entry_path)
                                if action == "cancel":
                                    return
                                elif action == "skip":
                                    continue
                                elif action == "skip_all":
                                    skip_all = True
                                    continue
                                elif action == "overwrite_all":
                                    overwrite_all = True

                            if not skip_all:
                                self.download_directory(remote_entry_path, local_entry_path, skip_all, overwrite_all)
                        else:
                            if not skip_all and not overwrite_all and os.path.exists(local_entry_path):
                                action = self.prompt_overwrite(local_entry_path)
                                if action == "cancel":
                                    return
                                elif action == "skip":
                                    continue
                                elif action == "skip_all":
                                    skip_all = True
                                    continue
                                elif action == "overwrite_all":
                                    overwrite_all = True

                            if not skip_all:
                                job_id = create_random_integer()
                                queue_item = QueueItem(remote_entry_path, job_id)
                                ic(remote_entry_path, local_entry_path)
                                ic(job_id)
                                add_sftp_job(remote_entry_path, True, local_entry_path, False, 
                                            self.init_hostname, self.init_username, 
                                            self.init_password, self.init_port, 
                                            "download", job_id)
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
        
        # Force refresh after upload/download operations
        self.model.invalidate_cache()
        self.model.get_files(force_refresh=True)

    def download_directory(self, source_directory, destination_directory, skip_all=False, overwrite_all=False):
        ic()

        try:
            # Create a local folder with the same name as the remote folder
            ic(source_directory, destination_directory)
            local_folder = destination_directory
            ic(local_folder)

            if not os.path.exists(local_folder):
                self.message_signal.emit(f"mkdir {local_folder}")
                os.makedirs(local_folder, exist_ok=True)

            # List the contents of the remote directory
            directory_contents = self.sftp_listdir(source_directory)
            ic(directory_contents)

            # Download files and recurse into subdirectories
            for entry in directory_contents:
                entry_path = self.get_normalized_remote_path(source_directory, entry)
                ic(entry_path)
                local_entry_path = os.path.join(local_folder, entry)

                ic(local_entry_path)
                if self.is_remote_directory(entry_path):
                    if not skip_all and not overwrite_all and os.path.exists(local_entry_path):
                        action = self.prompt_overwrite(local_entry_path)
                        if action == "cancel":
                            return
                        elif action == "skip":
                            continue
                        elif action == "skip_all":
                            skip_all = True
                            continue
                        elif action == "overwrite_all":
                            overwrite_all = True

                    if not skip_all:
                        self.message_signal.emit(f"download_directory() {entry_path}, {local_folder}")
                        self.download_directory(entry_path, local_entry_path, skip_all, overwrite_all)
                else:
                    # If it's a file, download it
                    self.message_signal.emit(f"download_directory() {entry_path}, {local_entry_path}")

                    if not skip_all and not overwrite_all and os.path.exists(local_entry_path):
                        action = self.prompt_overwrite(local_entry_path)
                        if action == "cancel":
                            return
                        elif action == "skip":
                            continue
                        elif action == "skip_all":
                            skip_all = True
                            continue
                        elif action == "overwrite_all":
                            overwrite_all = True

                    if not skip_all:
                        job_id = create_random_integer()
                        queue_item = QueueItem(os.path.basename(entry_path), job_id)
                        ic(job_id)
                        add_sftp_job(entry_path, True, local_entry_path, False, self.init_hostname, self.init_username, self.init_password, self.init_port, "download", job_id)

        except Exception as e:
            self.message_signal.emit(f"download_directory() {e}")
            ic(e)

        finally:
            self.notify_observers()
