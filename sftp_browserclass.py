from PyQt5.QtWidgets import QTableView, QApplication, QWidget, QVBoxLayout, QLabel, QFileDialog, QMessageBox, QInputDialog, QMenu, QHeaderView, QProgressBar, QSizePolicy
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtCore import pyqtSignal, QTimer, Qt, QEventLoop, QModelIndex, QUrl
from PyQt5 import QtCore
from stat import S_ISDIR
import stat
import os
from icecream import ic
from pathlib import Path
import subprocess  # Import subprocess for opening files

from sftp_creds import get_credentials, create_random_integer, set_credentials
from sftp_downloadworkerclass import create_response_queue, delete_response_queue, check_response_queue, add_sftp_job, QueueItem, queue

class Browser(QWidget):
    def __init__(self, title, session_id, parent=None):
        super().__init__(parent)  
        self.observers = []
        self.title = title
        self.model = None
        self.session_id = session_id
        self.user_choice = None
        self.init_global_creds()
        self.init_ui()
        self.always_continue_upload = False  # Initialize always_continue_upload

    def init_global_creds(self):
        creds = get_credentials(self.session_id)
        if creds is None:
            ic("No credentials found")
            self.init_hostname = "localhost"
            self.init_username = "guest"
            self.init_password = "guest"
            self.init_port = 22
        else:
            self.init_hostname = creds.get('hostname', "localhost")
            self.init_username = creds.get('username', "guest")
            self.init_password = creds.get('password', "guest")
            self.init_port = creds.get('port', 22)

    # Define a signal for sending messages to the console
    message_signal = pyqtSignal(str)

    def init_ui(self):
        self.layout = QVBoxLayout()
        self.label = QLabel(self.title)
        self.layout.addWidget(self.label)
        # Initialize and set the model for the table
        self.table = QTableView()

        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        # Enable sorting
        self.table.setSortingEnabled(True)

        # Connect signals and slots
        self.table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.table.doubleClicked.connect(self.double_click_handler)
        self.table.customContextMenuRequested.connect(self.context_menu_handler)
        # UI configuration
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.sortByColumn(0, Qt.AscendingOrder)

        self.layout.addWidget(self.table)  
        # Add the table and status bar to the layout
        self.progressBar = QProgressBar()
        self.layout.addWidget(self.progressBar)

        # Set the main layout of the widget
        self.setLayout(self.layout)

    def get_files(self):
        self.model.get_files()

    def add_observer(self,observer):
        if observer not in self.observers:
            self.observers.append(observer)
        else:
            ic("Observer already exists:", observer)

    def remove_observer(self,observer):
        if observer in self.observers:
            self.observers.remove(observer)

    def notify_observers(self):
            for observer in self.observers:
                try:
                    observer.get_files()  # Notify the observer by calling its update method
                except AttributeError as ae:
                    ic("Observer", observer, "does not implement 'get_files' method.", ae)
                except Exception as e:
                    ic("An error occurred while notifying observer", observer, e)

    def get_normalized_remote_path(self, current_remote_directory, partial_remote_path=None):
        """
        Get a normalized remote path by joining the current remote directory with a partial path.
        If no partial path is provided, return the normalized current remote directory.
        
        Args:
            current_remote_directory (str): The base directory on the remote server.
            partial_remote_path (str, optional): The partial path to be appended.
            
        Returns:
            str: The normalized remote path with forward slashes and no trailing slash.
        """
        # Replace backslashes with forward slashes in the base directory
        current_remote_directory = current_remote_directory.replace("\\", "/")

        if partial_remote_path is not None:
            # Replace backslashes with forward slashes in the partial path
            partial_remote_path = partial_remote_path.replace("\\", "/")
            
            # Join paths and normalize
            remote_path = os.path.join(current_remote_directory, partial_remote_path)
            normalized_path = os.path.normpath(remote_path)
        else:
            # Normalize the current remote directory
            normalized_path = os.path.normpath(current_remote_directory)
        
        # Convert backslashes to forward slashes in the final path
        normalized_path = normalized_path.replace("\\", "/")
        
        # Remove the trailing slash if it's not the root '/'
        if normalized_path != '/':
            normalized_path = normalized_path.rstrip('/')
        
        return normalized_path

    def is_complete_path(self, path):
        """
        Determine if a path is a complete path or just a filename/directory name.
        
        Args:
            path (str): The filesystem path to check.
            
        Returns:
            bool: True if the path is a complete path, False if it's just a filename/directory name.
        """
        # Convert to a Path object for easier manipulation
        p = Path(path)
        
        # Check if it's an absolute path or starts with a '/' (Unix-like absolute path)
        if p.is_absolute() or path.startswith('/'):
            return True
        
        # Check if it has more than one part (indicating it's not just a simple name)
        if len(p.parts) > 1:
            return True
        
        # Check if it ends with a slash (indicating it's intended as a directory name)
        if path.endswith('/') or path.endswith('\\'):
            return False
        
        # It's likely just a name if none of the above conditions are met
        return False        

    def split_path(self, path):
        # try to deal with windows backslashes
        if "\\" in path:
            # Use "\\" as the separator
            head, tail = path.rsplit("\\", 1)
        elif "/" in path:
            # Use "/" as the separator
            head, tail = path.rsplit("/", 1)
        else:
            # No "\\" or "/" found, assume the entire string is the head
            head, tail = path, ""

        return head, tail

    def sftp_mkdir(self, remote_path):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "mkdir", job_id )

        while queue.empty():
            self.non_blocking_sleep(100)

        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_mkdir() {error}")
            f = False
        else:
            # if its a success then we dont care about the response and the queue will be deleted
            f = True

        delete_response_queue(job_id)
        self.model.get_files()
        self.notify_observers()
        return f

    def sftp_rmdir(self, remote_path):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "rmdir", job_id )

        while queue.empty():
            self.non_blocking_sleep(100)
        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_rmdir() {error}")
            f = False
        else:
            f = True

        delete_response_queue(job_id)
        self.get_files()
        self.notify_observers()
        return f

    def sftp_remove(self, remote_path ):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "remove", job_id )

        while queue.empty():
            self.non_blocking_sleep(100)
        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_remove() {error}")
            f = False
        else:
            f = True

        delete_response_queue(job_id)
        self.get_files()
        self.notify_observers()
        return f

    def sftp_listdir(self, remote_path ):
        ic()
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "listdir", job_id )

        self.progressBar.setRange(0, 0)
        while queue.empty():
            self.non_blocking_sleep(100)  # Sleeps for 1000 milliseconds (1 second)
        response = queue.get_nowait()
        self.progressBar.setRange(0, 100)

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_listdir() {error}")
            f = False
        else:
            list = queue.get_nowait()
            f = True

        delete_response_queue(job_id)
        if f:
            return list
        else:
            return f

    def non_blocking_sleep(self, ms):
        # special sleep function that can be used by a background/foreground thread, without causing a hang

        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec_()

    def sftp_listdir_attr(self, remote_path ):
        creds = get_credentials(self.session_id)
        # get remote directory listing with attributes from the remote_path

        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "listdir_attr", job_id )

        while queue.empty():
            self.non_blocking_sleep(100)
        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_listdir_attr() {error}")
            f = False
        else:
            list = queue.get_nowait()
            f = True

        delete_response_queue(job_id)
        if f:
            return list
        else:
            return f

    def normalize_path(self, path):
        """
        Normalize the given path by collapsing redundant slashes and up-level references.
        
        Args:
            path (str): The filesystem path to normalize.
            
        Returns:
            str: The normalized path.
        """
        return os.path.normpath(path)

    def on_header_clicked(self, logicalIndex):
        # Check the current sort order and toggle it
        # not the best, should really be revised 
        order = Qt.DescendingOrder if self.table.horizontalHeader().sortIndicatorOrder() == Qt.AscendingOrder else Qt.AscendingOrder
        self.table.sortByColumn(logicalIndex, order)

    def is_remote_directory(self, partial_remote_path):
        is_directory = False
        
        try:
            # Retrieve credentials once
            creds = get_credentials(self.session_id)

            # Normalize the path
            if not self.is_complete_path(partial_remote_path):
                remote_path = self.get_normalized_remote_path(creds.get('current_remote_directory'), partial_remote_path)
            else:
                remote_path = self.get_normalized_remote_path(partial_remote_path)
            
        except Exception as e:
            self.message_signal.emit(f"Error in getting credentials or forming remote path: {e}")
            ic(e)
            return False

        # Create job and response queue
        job_id = create_random_integer()
        queue = create_response_queue(job_id)
        
        try:
            add_sftp_job(
                remote_path, True,
                remote_path, True,
                creds.get('hostname'), creds.get('username'), creds.get('password'),
                creds.get('port'), "stat", job_id
            )

            # Wait for a response
            while queue.empty():
                self.non_blocking_sleep(100)
            
            response = queue.get_nowait()

            if response == "error":
                error = queue.get_nowait()
                self.message_signal.emit(f"SFTP job error: {error}")
                ic(error)
                return False

            # Extract attributes correctly from response
            attributes = queue.get_nowait()
            if stat.S_ISDIR(attributes.st_mode):
                is_directory = True
        
        except queue.Empty:
            self.message_signal.emit("Queue was empty unexpectedly.")
            is_directory = False
        except Exception as e:
            self.message_signal.emit(f"Unexpected error: {e}")
            ic(e)
            is_directory = False
        finally:
            delete_response_queue(job_id)
            return is_directory


    def is_remote_file(self, partial_remote_path):
        is_file = False
        
        try:
            # Retrieve credentials once
            creds = get_credentials(self.session_id)

            # Normalize the path
            if not self.is_complete_path(partial_remote_path):
                remote_path = self.get_normalized_remote_path(creds.get('current_remote_directory'), partial_remote_path)
            else:
                remote_path = self.get_normalized_remote_path(partial_remote_path)
            
        except Exception as e:
            self.message_signal.emit(f"Error in getting credentials or forming remote path: {e}")
            ic(e)
            return False

        # Create job and response queue
        job_id = create_random_integer()
        queue = create_response_queue(job_id)
        
        try:
            add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "stat", job_id)

            # Wait for a response
            while queue.empty():
                self.non_blocking_sleep(100)

            response = queue.get_nowait()

            if response != "error":
                attributes = queue.get_nowait()
                ic(attributes)
                is_directory = S_ISDIR(attributes.st_mode)
                is_file = not is_directory
            else:
                error = queue.get_nowait()
                ic(error)
                is_file = False

        except FileNotFoundError:
            is_file = False

        except Exception as e:
            self.message_signal.emit(f"FileBrowser is_remote_file() {e}")
            is_file = False

        finally:
            delete_response_queue(job_id)
            return is_file

    def waitjob(self, job_id):
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)

        progress_value = 0
        while not check_response_queue(job_id):
            progress_value = min(progress_value + 10, 100)
            self.progressBar.setValue(progress_value)
            self.non_blocking_sleep(100)
            QApplication.processEvents()

        self.progressBar.setValue(100)
        self.progressBar.setRange(0, 100)
        return

    def focusInEvent(self, event):
        self.setStyleSheet("""
            QTableWidget {
            background-color: #ffffff; /* Set background color */
            color: white;  /* Text color */
            border: 1px solid #cccccc; /* Add a thin border */
            selection-background-color: #e0e0e0; /* Set background color for selected items */
            }
        """)
        self.label.repaint()  # Force a repaint

    def focusOutEvent(self, event):
        self.setStyleSheet("""
            QTableWidget {
            background-color: #777777; /* Set background color */
            color: gray;  /* Text color */
            border: 1px solid #999999; /* Add a thin border */
            selection-background-color: #909090; /* Set background color for selected items */
            }
        """)
        self.label.repaint()  # Force a repaint

    def prompt_and_create_directory(self):
        creds = get_credentials(self.session_id)

        # Prompt the user for a new directory name
        directory_name, ok = QInputDialog.getText(
            None,
            'Create New Directory',
            'Enter the name of the new directory:'
        )

        if ok and directory_name:
            directory_path = os.path.join(creds.get('current_local_directory'), directory_name)

            try:
                # Attempt to create the directory locally
                os.makedirs(directory_path)
                self.message_signal.emit(f"Directory '{directory_path}' created successfully.")

            except Exception as e:
                QMessageBox.critical(None, 'Error', f"Error creating directory: {e}")
                self.message_signal.emit(f"Error creating directory: {e}")

            finally:
                self.model.get_files()
                self.notify_observers()

    def change_directory_handler(self):
        selected_path, ok = QInputDialog.getText(self, 'Input Dialog', 'Enter directory name:')

        if not ok:
            return

        try:
            is_directory = os.path.isdir(selected_path)

            if is_directory:
                # Call the method to change the directory
                self.change_directory(selected_path)

        except Exception as e:
            # Append error message to the output_console
            self.message_signal.emit(f"change_directory_handler() {e}")

        finally:
            self.model.get_files()
            self.notify_observers()

    def change_directory(self, path ):
        # this is a function to change the current LOCAL working directory, it also uses this moment to refresh the local file list

        try:
            # Local file browser
            os.chdir(path)
            set_credentials(self.session_id, 'current_local_directory', os.getcwd() )
            self.model.get_files()
            self.notify_observers()
        except Exception as e:
            # Append error message to the output_console
            self.message_signal.emit(f"change_directory() {e}")

    def double_click_handler(self, index):
        creds = get_credentials(self.session_id)

        if index.isValid():
            path = self.model.data(index, Qt.DisplayRole)

        try:
            if path == "..":
                head, tail = self.split_path(creds.get('current_local_directory'))
                new_path = head
            else:
                new_path = os.path.join(creds.get('current_local_directory'), path)

            is_directory = os.path.isdir(new_path)
            if is_directory:
                self.change_directory(new_path)
            else:
                if self.is_remote_browser():
                    remote_path, _ = QFileDialog.getSaveFileName(self, "Select Local Location", os.path.basename(path))
                    if remote_path:
                        self.upload_download(remote_path, path)
                else:
                    remote_path, _ = QFileDialog.getSaveFileName(self, "Select Remote Location", os.path.basename(path))
                    if remote_path:
                        self.upload_download(new_path, remote_path)

        except Exception as e:
            self.message_signal.emit(f"double_click_handler() {e}")

    def context_menu_handler(self, point):
        current_browser = self.focusWidget()
        if current_browser is not None:
            menu = QMenu(self)
            remove_dir_action = menu.addAction("Remove Directory")
            change_dir_action = menu.addAction("Change Directory") 
            upload_download_action = menu.addAction("Upload/Download")
            prompt_and_create_directory = menu.addAction("Create Directory")
            view_action = menu.addAction("View")

            remove_dir_action.triggered.connect(self.remove_directory_with_prompt)
            change_dir_action.triggered.connect(self.change_directory_handler)  
            upload_download_action.triggered.connect(self.upload_download)
            prompt_and_create_directory.triggered.connect(self.prompt_and_create_directory)
            view_action.triggered.connect(self.view_item)

            menu.exec_(current_browser.mapToGlobal(point))

    def upload_download(self, remote_path=None, local_path=None):
        creds = get_credentials(self.session_id)

        current_browser = self.focusWidget()

        if current_browser is not None and isinstance(current_browser, QTableView):
            indexes = current_browser.selectedIndexes()
            has_valid_item = False

            for index in indexes:
                selected_item_text = ""

                if isinstance(index, QModelIndex):
                    if index.isValid():
                        selected_item_text = current_browser.model().data(index, Qt.DisplayRole)
                elif isinstance(index, str):
                    selected_item_text = index

                if selected_item_text:
                    if not self.is_complete_path(selected_item_text):
                        if self.is_remote_browser():
                            # Downloading from remote to local
                            if remote_path is None:
                                remote_path, _ = QFileDialog.getSaveFileName(self, "Select Local Location", selected_item_text)
                                if remote_path is None:
                                    return
                            selected_path = self.get_normalized_remote_path(creds.get('current_remote_directory'), selected_item_text)
                        else:
                            # Uploading from local to remote
                            if local_path is None:
                                local_path, _ = QFileDialog.getOpenFileName(self, "Select Local File", "", "All Files (*.*)")
                                if local_path is None:
                                    return
                            selected_path = os.path.join(creds.get('current_local_directory'), selected_item_text)
                            remote_path = self.get_normalized_remote_path(creds.get('current_remote_directory'), selected_item_text)
                    else:
                        if self.is_remote_browser():
                            # Downloading from remote to local
                            selected_path = self.get_normalized_remote_path(selected_item_text)
                            if remote_path is None:
                                remote_path, _ = QFileDialog.getSaveFileName(self, "Select Local Location", selected_item_text)
                                if remote_path is None:
                                    return
                        else:
                            # Uploading from local to remote
                            selected_path = self.normalize_path(selected_item_text)
                            if local_path is None:
                                local_path, _ = QFileDialog.getOpenFileName(self, "Select Local File", "", "All Files (*.*)")
                                if local_path is None:
                                    return
                            remote_path = self.get_normalized_remote_path(creds.get('current_remote_directory'), selected_item_text)

                    try:
                        if os.path.isdir(selected_path):
                            self.message_signal.emit(f"Transferring directory: {selected_path}")
                            if self.is_remote_browser():
                                self.download_directory(selected_path, remote_path)
                            else:
                                self.upload_directory(selected_path, remote_path)
                        else:
                            if self.is_remote_browser():
                                self.message_signal.emit(f"Downloading file: {selected_path}")
                            else:
                                self.message_signal.emit(f"Uploading file: {selected_path}")
                            job_id = create_random_integer()
                            queue_item = QueueItem(os.path.basename(selected_path), job_id)
                            if self.is_remote_browser():
                                add_sftp_job(selected_path, True, remote_path, False, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "download", job_id)
                            else:
                                add_sftp_job(selected_path, False, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "upload", job_id)
                        has_valid_item = True 
                    except Exception as e:
                        self.message_signal.emit(f"upload_download() encountered an error: {e}")
                else:
                    self.message_signal.emit("Invalid item or empty path.")
            
            if not has_valid_item:
                self.message_signal.emit("No valid items selected.")
        else:
            self.message_signal.emit("Current browser is not a valid QTableView.")

    def download_directory(self, remote_directory, local_directory, always=0):
        self.always = always
        creds = get_credentials(self.session_id)
        try:
            local_folder = local_directory

            target_exists = os.path.isdir(local_folder)

            if target_exists and not self.always:
                response = self.show_prompt_dialog(f"The folder {local_folder} already exists. Do you want to continue downloading?", "Download Confirmation")

                if response == QMessageBox.No:
                    return
                elif response == QMessageBox.Yes:
                    pass  # Continue with the download
                elif response == QMessageBox.YesToAll:
                    self.always = 1
                else:
                    return
            else:
                try:
                    os.makedirs(local_folder, exist_ok=True)
                except Exception as e:
                    self.message_signal.emit(f"{e}")
                    pass

            remote_contents = self.sftp_listdir(remote_directory)

            if not remote_contents:
                self.message_signal.emit(f"No files found in {remote_directory}")
                return

            for entry in remote_contents:
                remote_entry_path = self.get_normalized_remote_path(remote_directory, entry)
                local_entry_path = os.path.join(local_folder, entry)

                job_id = create_random_integer()

                if self.is_remote_directory(remote_entry_path):
                    self.download_directory(remote_entry_path, local_entry_path, self.always)
                else:
                    queue_item = QueueItem( os.path.basename(entry), job_id )
                    add_sftp_job(remote_entry_path, True, local_entry_path, False, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "download", job_id)

        except Exception as e:
            self.message_signal.emit(f"download_directory() {e}")

        finally:
            self.notify_observers()

    def upload_directory(self, source_directory, destination_directory, always=0):
        self.always = always
        creds = get_credentials(self.session_id)

        try:
            remote_folder = destination_directory

            target_exists = self.sftp_exists(remote_folder)

            if target_exists and self.is_remote_directory(remote_folder) and not self.always:
                response = self.show_prompt_dialog(f"The folder {remote_folder} already exists. Do you want to continue uploading?", "Upload Confirmation")

                if response == QMessageBox.No:
                    return
                elif response == QMessageBox.Yes:
                    pass  # Continue with the upload
                elif response == QMessageBox.YesToAll:
                    self.always = 1
                else:
                    return
            else:
                try:
                    success = self.sftp_mkdir(remote_folder) 
                    self.notify_observers()                    
                    if not success or self.always_continue_upload:
                        self.message_signal.emit(f"sftp_mkdir() error creating {remote_folder} but always_continue_upload is {self.always_continue_upload}")
                        return
                except Exception as e:
                    self.message_signal.emit(f"{e}")
                    pass

            local_contents = os.listdir(source_directory)

            for entry in local_contents:
                entry_path = os.path.join(source_directory, entry)
                remote_entry_path = self.get_normalized_remote_path(remote_folder, entry)

                job_id = create_random_integer()

                if os.path.isdir(entry_path):
                    queue_item = QueueItem( os.path.basename(entry_path), job_id )
                    self.sftp_mkdir(remote_entry_path)
                    self.get_files()
                    self.upload_directory(entry_path, remote_entry_path, self.always)
                else:
                    self.message_signal.emit(f"{entry_path}, {remote_entry_path}")

                    queue_item = QueueItem( os.path.basename(entry_path), job_id )

                    add_sftp_job(entry_path, False, remote_entry_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "upload", job_id)

        except Exception as e:
            self.message_signal.emit(f"upload_directory() {e}")
        
        finally:
            self.notify_observers()

    def show_prompt_dialog(self, text, title):
        dialog = QMessageBox(self.parent())
        dialog.setWindowTitle(title)
        dialog.setText(text)
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll)
        dialog.setDefaultButton(QMessageBox.Yes)

        return dialog.exec_()

    def view_file(self):
        current_index = self.table.currentIndex()
        if current_index.isValid():
            file_name = self.model.data(current_index, Qt.DisplayRole)
            file_path = os.path.join(self.model.directory, file_name)
            if os.path.isfile(file_path):
                self.open_file_with_default_app(file_path)

    def open_file_with_default_app(self, file_path):
        try:
            if os.name == 'nt':  # For Windows
                os.startfile(file_path)
            elif os.name == 'posix':  # For macOS and Linux
                subprocess.call(('open', file_path))
        except Exception as e:
            self.message_signal.emit(f"Error opening file: {str(e)}")

    def view_item(self):
        current_browser = self.focusWidget()
        if current_browser is not None and isinstance(current_browser, QTableView):
            current_index = current_browser.currentIndex()
            if current_index.isValid():
                selected_item = current_browser.model().data(current_index, Qt.DisplayRole)
                creds = get_credentials(self.session_id)
                if self.is_remote_browser():
                    local_path = os.path.join(os.path.expanduser("~"), "Downloads", selected_item)
                    remote_path = self.get_normalized_remote_path(creds.get('current_remote_directory'), selected_item)
                    # Start the download
                    self.upload_download(remote_path=remote_path, local_path=local_path)
                    # Use the finished signal to open the file
                    self.wait_for_download_completion(selected_item) 
                else:
                    full_path = os.path.join(creds.get('current_local_directory'), selected_item)
                    QDesktopServices.openUrl(QUrl.fromLocalFile(full_path))

    def wait_for_download_completion(self, selected_item):
        # Wait for the download to finish
        while not check_response_queue(self.last_download_job_id):
            self.non_blocking_sleep(100)
            QApplication.processEvents()

        # Open the downloaded file
        local_path = os.path.join(os.path.expanduser("~"), "Downloads", selected_item)
        QDesktopServices.openUrl(QUrl.fromLocalFile(local_path))

    def sftp_exists(self, path):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        try:
            add_sftp_job(path, True, path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "stat", job_id )

            while queue.empty():
                self.non_blocking_sleep(100)
            response = queue.get_nowait()

            if response == "error":
                error = queue.get_nowait() # get error message
                self.message_signal.emit(f"sftp_exists() {error}")
                raise error
            else: # success means what it is it exists
                exist = True

        except Exception as e:
            self.message_signal.emit(f"sftp_exists() {e}")
            exist = False

        finally:
            delete_response_queue(job_id)
            return exist
    def is_remote_browser(self):
        return "Remote" in self.title

    def remove_directory_with_prompt(self):
        creds = get_credentials(self.session_id)
        current_browser = self.focusWidget()

        if current_browser is not None and isinstance(current_browser, QTableView):
            indexes = current_browser.selectedIndexes()

            for index in indexes:
                if index.isValid():
                    selected_item_text = current_browser.model().data(index, Qt.DisplayRole)

                    if selected_item_text:
                        if not self.is_complete_path(selected_item_text):
                            selected_path = os.path.join(creds.get('current_local_directory'), selected_item_text)
                        else:
                            selected_path = self.normalize_path(selected_item_text)

                        if self.is_remote_browser():
                            # Remove remote directory
                            if self.is_remote_directory(selected_path):
                                response = QMessageBox.question(self, "Confirm Remove Directory", f"Are you sure you want to remove the directory: {selected_path}?", QMessageBox.Yes | QMessageBox.No)
                                if response == QMessageBox.Yes:
                                    self.remove_directory(selected_path)
                            else:
                                response = QMessageBox.question(self, "Confirm Remove File", f"Are you sure you want to remove the file: {selected_path}?", QMessageBox.Yes | QMessageBox.No)
                                if response == QMessageBox.Yes:
                                    self.remove_file(selected_path)
                        else:
                            # Remove local directory
                            if os.path.isdir(selected_path):
                                response = QMessageBox.question(self, "Confirm Remove Directory", f"Are you sure you want to remove the directory: {selected_path}?", QMessageBox.Yes | QMessageBox.No)
                                if response == QMessageBox.Yes:
                                    self.remove_directory(selected_path)
                            else:
                                response = QMessageBox.question(self, "Confirm Remove File", f"Are you sure you want to remove the file: {selected_path}?", QMessageBox.Yes | QMessageBox.No)
                                if response == QMessageBox.Yes:
                                    self.remove_file(selected_path)

    def remove_directory(self, path):
        try:
            if self.is_remote_browser():
                self.sftp_rmdir(path)
            else:
                os.rmdir(path)
        except Exception as e:
            self.message_signal.emit(f"remove_directory() {e}")

    def remove_file(self, path):
        try:
            if self.is_remote_browser():
                self.sftp_remove(path)
            else:
                os.remove(path)
        except Exception as e:
            self.message_signal.emit(f"remove_file() {e}")

    def adjust_window_size(self):
        # Calculate the ideal height based on the number of transfers
        ideal_height = 200 + (len(self.transfers) * 75)  # 200 for other widgets, 50 per transfer
        max_height = 600  # Set a maximum height
        new_height = min(ideal_height, max_height)
        self.resize(self.width(), new_height)