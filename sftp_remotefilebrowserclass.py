from sftp_filebrowserclass import FileBrowser
from PyQt5.QtWidgets import QTableView, QFileDialog, QMessageBox, QInputDialog, QHeaderView
from PyQt5.QtCore import Qt
from icecream import ic
import os
import stat

from sftp_remotefiletablemodel import RemoteFileTableModel
from sftp_creds import get_credentials, create_random_integer, set_credentials, create_random_integer
from sftp_downloadworkerclass import create_response_queue, delete_response_queue, add_sftp_job, QueueItem
from sftp_backgroundthreadwindow import queue_display_append

class RemoteFileBrowser(FileBrowser):
    def __init__(self, title, session_id, parent=None):
        super().__init__(title, session_id, parent)  # Initialize the FileBrowser parent class
        # ic("init remote file browser")
        self.model = RemoteFileTableModel(self.session_id)

        # ic("init model complete")
        self.table.setModel(self.model)
        # Set horizontal scroll bar policy for the entire table
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # Resize the first column based on its contents
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        ic("init set current remote dir")

        set_credentials(self.session_id, 'current_remote_directory', self.sftp_getcwd())

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
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue( job_id )

        ic("sftp_getcwd")
        ic(creds)

        try:
            add_sftp_job(creds.get('current_remote_directory'), True, ".", True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "getcwd", job_id)
        except Exception as e:
            ic(e)

        ic("waiting")
        while queue.empty():
            self.non_blocking_sleep(100)  # Sleeps for 1000 milliseconds (1 second)
        response = queue.get_nowait()
        ic("response")

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
                # ic(response)
                raise response
            else:
                # if success, set our new remote working path to the newly created path path that we path'd pathily'
                set_credentials(self.session_id, 'current_remote_directory', new_path)

            self.message_signal.emit(f"{new_path}")
            self.model.get_files()
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
        # ic("RemoteFileBrowser double_click_handler")
        try:
            if index.isValid():
                # Retrieve the file path from the model
                # ic("RemoteFileBrowser double_click_handler index.isValid()")
                temp_path = self.model.data(index, Qt.DisplayRole)

                if temp_path != "..":
                    # ic("RemoteFileBrowser double_click_handler temp_path != ..")
                    path = os.path.join( creds.get('current_remote_directory'), temp_path )
                    if self.is_remote_directory(temp_path):
                        ic("doubleclickhandler change directory?")
                        self.change_directory(path.replace("\\", "/"))
                    elif self.is_remote_file(temp_path):
                        ic("RemoteFileBrowser double_click_handler is_remote_file()")
                        local_path = QFileDialog.getSaveFileName(self, "Save File", os.path.basename(temp_path))[0]
                        if local_path:
                            # Assuming upload_download is a method to handle the download
                            ic("doubleclickhandler uploaddownload")
                            self.upload_download(local_path)
                            # Emit a signal or log the download
                            self.message_signal.emit(f"Downloaded file: {path} to {local_path}")
                if temp_path == "..":
                    ic("RemoteFileBrowser double_click_handler temp_path == ..")
                    ic("doubleclickhandler go up a dir")
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
        creds = get_credentials(self.session_id)

        if remote_path == None or remote_path == False:
            current_browser = self.focusWidget()
            if current_browser is not None:
                current_index = current_browser.currentIndex()
                if current_index.isValid():
                    # Assuming the first column holds the item text you need
                    selected_item = current_browser.model().data(current_index, Qt.DisplayRole)
                    if creds.get('current_remote_directory') == '.':
                        temp_path = self.sftp_getcwd()
                    set_credentials(self.session_id, 'current_remote_directory', self.remove_trailing_dot(temp_path))
                    remote_path = os.path.join( creds.get('current_remote_directory'), selected_item )
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
                self.message_signal.emit(f"Removing file: {entry_path}")
                self.sftp_remove(entry_path)

            # Recursively remove subdirectories
            for entry in subdirectories:
                entry_path = os.path.join(remote_path, entry.filename)
                self.message_signal.emit(f"Recursing into subdirectory: {entry_path}")
                self.remove_directory_with_prompt(entry_path)


            # Remove the directory
            self.sftp_rmdir(remote_path)
            self.message_signal.emit(f"Directory '{remote_path}' removed successfully.")
            self.model.get_files()

        except Exception as e:
            self.message_signal.emit(f"remove_directory_with_prompt() {e}")

    def upload_download(self):
        creds = get_credentials(self.session_id)
        if creds.get('current_remote_directory') == '.':
            set_credentials( self.session_id, 'current_remote_directory', self.sftp_getcwd())
            creds = get_credentials(self.session_id)
        current_browser = self.focusWidget()

        if current_browser is not None and isinstance(current_browser, QTableView):
            index = current_browser.currentIndex()
            if index.isValid():
                selected_item_text = current_browser.model().data(index, Qt.DisplayRole)

                if selected_item_text:
                    selected_path = selected_item_text  # Assuming this is the full path or relative path

                    try:
                        # local_entry_path = os.path.join(os.getcwd(), os.path.basename(selected_path))
                        entry_path = os.path.join( creds.get('current_remote_directory'), os.path.basename(selected_path))
                        local_path = os.path.join( os.getcwd(), os.path.basename(selected_path))

                        ic("remotefilebrowser uploaddownload is remote directory")
                        if self.is_remote_directory(entry_path):
                            # Download directory
                            ic("    yes remote directory")
                            self.download_directory(entry_path, local_path)
                        else:
                            # Download file
                            ic("    no remote file")
                            job_id = create_random_integer()
                            queue_item = QueueItem(entry_path, job_id)
                            queue_display_append(queue_item)
                            ic("adding remote file to download job queue")
                            ic(job_id)
                            add_sftp_job(entry_path, True, local_path, False, self.init_hostname, self.init_username, self.init_password, self.init_port, "download", job_id)
                    except Exception as e:
                        self.message_signal.emit(f"upload_download() {e}")
                        ic(e)
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
                    queue_display_append(queue_item)
                    ic("add_sftp_job")
                    ic(job_id)
                    add_sftp_job(entry_path.replace("\\", "/"), True, local_entry_path, False, self.init_hostname, self.init_username, self.init_password, self.init_port, "download", job_id)

        except Exception as e:
            self.message_signal.emit(f"download_directory() {e}")
            ic(e)