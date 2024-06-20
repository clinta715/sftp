from PyQt5.QtWidgets import QTableView, QApplication, QWidget, QVBoxLayout, QLabel, QFileDialog, QMessageBox, QInputDialog, QMenu, QHeaderView, QProgressBar, QSizePolicy
from PyQt5.QtCore import pyqtSignal, QTimer, Qt, QEventLoop
from PyQt5 import QtCore
from stat import S_ISDIR
import os
from icecream import ic

from sftp_creds import get_credentials, create_random_integer, set_credentials
from sftp_downloadworkerclass import create_response_queue, delete_response_queue, check_response_queue, add_sftp_job, QueueItem, queue
from sftp_backgroundthreadwindow import queue_display_append

class Browser(QWidget):
    def __init__(self, title, session_id, parent=None):
        super().__init__(parent)  # Initialize the QWidget parent class
        self.title = title
        self.model = None
        self.session_id = session_id
        self.user_choice = None
        ic("browser class init complete 1")
        self.init_global_creds()
        ic("init global creds done")
        self.init_ui()

    def init_global_creds(self):
        # ic("init_global_creds")
        creds = get_credentials(self.session_id)
        # ic(creds)
        # ic("init global creds 2")
        try:
            self.init_hostname = creds.get('hostname')
        except Exception as e:
            ic(e)

        # ic("init global creds 3")
        self.init_username = creds.get('username')
        # ic("init global creds 4")
        self.init_password = creds.get('password')
        # ic("init global creds 5")
        self.init_port = creds.get('port')

    # Define a signal for sending messages to the console
    message_signal = pyqtSignal(str)

    def init_ui(self):
        self.layout = QVBoxLayout()
        self.label = QLabel(self.title)
        self.layout.addWidget(self.label)
        # ic("init ui browser 1")
        # Initialize and set the model for the table
        self.table = QTableView()

        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        # ic("init ui browser 2")
        # Enable sorting
        self.table.setSortingEnabled(True)

        # Connect signals and slots
        self.table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.table.doubleClicked.connect(self.double_click_handler)
        self.table.customContextMenuRequested.connect(self.context_menu_handler)
        # ic("init ui browser 3")
        # UI configuration
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.sortByColumn(0, Qt.AscendingOrder)

        self.layout.addWidget(self.table)  # Correctly add the table to the layout
        # ic("init ui browser 4")
        # Add the table and status bar to the layout
        self.progressBar = QProgressBar()
        self.layout.addWidget(self.progressBar)

        # Set the main layout of the widget
        self.setLayout(self.layout)
        # ic("browser class ui init complete 2")

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

        add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "mkdir", job_id )

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

        self.model.get_files()
        delete_response_queue(job_id)
        return f

    def sftp_rmdir(self, remote_path):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "rmdir", job_id )

        while queue.empty():
            self.non_blocking_sleep(100)
        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_rmdir() {error}")
            f = False
        else:
            f = True

        self.model.get_files()
        delete_response_queue(job_id)
        return f

    def sftp_remove(self, remote_path ):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "remove", job_id )

        while queue.empty():
            self.non_blocking_sleep(100)
        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_remove() {error}")
            f = False
        else:
            f = True

        self.model.get_files()
        delete_response_queue(job_id)
        return f

    def sftp_listdir(self, remote_path ):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "listdir", job_id )

        self.progressBar.setRange(0, 0)
        while check_response_queue(job_id).empty():
            self.non_blocking_sleep(100)  # Sleeps for 1000 milliseconds (1 second)
        response = queue.get_nowait()
        self.progressBar.setRange(0, 100)

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_listdir() {error}")
            # ic(error)
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

        add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "listdir_attr", job_id )

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

    def on_header_clicked(self, logicalIndex):
        # Check the current sort order and toggle it
        # not the best, should really be revised 
        order = Qt.DescendingOrder if self.table.horizontalHeader().sortIndicatorOrder() == Qt.AscendingOrder else Qt.AscendingOrder
        self.table.sortByColumn(logicalIndex, order)

    def is_remote_directory(self, partial_remote_path ):
        ic("is remote directory")
        ic(partial_remote_path)
        creds = get_credentials(self.session_id)
        # check to see if remote_path is in fact a file or a directory on the current remote connection 
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        remote_path = creds.get('current_remote_directory') + "/" + partial_remote_path
        ic(remote_path)

        try:
            add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "stat", job_id )

            while queue.empty():
                self.non_blocking_sleep(100)
            response = queue.get_nowait()

            if not response == "error":
                attributes = queue.get_nowait()
                is_directory = S_ISDIR(attributes.st_mode)
                ic(is_directory)
            else:
                error = queue.get_nowait()
                self.message_signal.emit(f"FileBrowser is_remote_directory() {error}")
                ic(error)
                is_directory = False

        except Exception as e:
            self.message_signal.emit(f"FileBrowser is_remote_directory() {e}")
            ic(e)
            is_directory = False

        finally:
            ic(is_directory)
            delete_response_queue(job_id)
            if is_directory:
                return True
            else:
                return False

    def is_remote_file(self, remote_path ):
        # ic("Is remote file")
        creds = get_credentials(self.session_id)
        # check to see if remote_path is in fact a file or a directory on the current remote connection
        job_id = create_random_integer()
        queue = create_response_queue( job_id )

        try:
            # ic("add job")
            add_sftp_job(remote_path.replace("\\", "/"), True, remote_path.replace("\\", "/"), True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "stat", job_id )

            while queue.empty():
                self.non_blocking_sleep(100)
            response = queue.get_nowait()
            # ic(response)

            if not response == "error":
                attributes = queue.get_nowait()
                is_directory = S_ISDIR(attributes.st_mode)
                if is_directory:
                    is_file = False
            else:
                error = queue.get_nowait()
                is_file = False

        except FileNotFoundError:
            # If the file doesn't exist, treat it as not a file
            is_file = False

        except Exception as e:
            # Handle other exceptions (e.g., permission denied, etc.) if needed
            self.message_signal.emit(f"FileBrowser is_remote_file() {e}")
            is_file = False

        finally:
            # ic(is_file)
            delete_response_queue(job_id)
            return is_file

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

    def change_directory(self, path ):
        # this is a function to change the current LOCAL working directory, it also uses this moment to refresh the local file list

        try:
            # Local file browser
            os.chdir(path)
            set_credentials(self.session_id, 'current_local_directory', os.getcwd() )
            self.model.get_files()  # Update local file browser with new directory contents
        except Exception as e:
            # Append error message to the output_console
            self.message_signal.emit(f"change_directory() {e}")

    def double_click_handler(self, index):
        # this function tries to figure out, more or less sans a lot of context, what 'index' is pointing at and then, what to do with it
        # my logic here was, if its a directory change to it, if its a file transfer it
        # if its a local file, probably want to upload it, if its a remote file, probably want to download it
        creds = get_credentials(self.session_id)

        if index.isValid():
            # Retrieve the data from the model
            path = self.model.data(index, Qt.DisplayRole)
            # Now you can use 'text' as needed

        try:
            if path == "..":
                head, tail = self.split_path(creds.get('current_local_directory'))
                new_path = head
                # ic(new_path)
            else:
                new_path = os.path.join(creds.get('current_local_directory'), path)  # Assuming the text of the item contains the file path

            # Check if the item is a directory
            is_directory = os.path.isdir(new_path)
            if is_directory:
                # Change the current working directory or perform other actions
                self.change_directory(new_path)
            else:
                # Upload the file to the remote server
                remote_path, _ = QFileDialog.getSaveFileName(self, "Select Remote Location", os.path.basename(path))
                if remote_path:
                    self.upload_download(new_path)

        except Exception as e:
            # Append error message to the output_console
            self.message_signal.emit(f"double_click_handler() {e}")

    def context_menu_handler(self, point):
        # If point is not provided, use the center of the list widget
        if not point:
            point = self.file_list.rect().center()

        # Get the currently focused widget
        current_browser = self.focusWidget()
        if current_browser is not None:
            menu = QMenu(self)
            # Add actions to the menu
            remove_dir_action = menu.addAction("Remove Directory")
            change_dir_action = menu.addAction("Change Directory")  # New action
            upload_download_action = menu.addAction("Upload/Download")
            prompt_and_create_directory = menu.addAction("Create Directory")

            # Connect the actions to corresponding methods
            remove_dir_action.triggered.connect(self.remove_directory_with_prompt)
            change_dir_action.triggered.connect(self.change_directory_handler)  # Connect to the new method
            upload_download_action.triggered.connect(self.upload_download)
            prompt_and_create_directory.triggered.connect(self.prompt_and_create_directory)

            # Show the menu at the cursor position
            menu.exec_(current_browser.mapToGlobal(point))

    def upload_download(self):
        # based on what the user clicked, let's decide if it's a local file needing uploading or a remote file needing downloading
        creds = get_credentials(self.session_id)

        current_browser = self.focusWidget()
        # did they click the local or remote browser

        if current_browser is not None and isinstance(current_browser, QTableView):
            index = current_browser.currentIndex()
            # what thing did they click in that browser
            if index.isValid():
                # and now, what is that thing?!
                selected_item_text = current_browser.model().data(index, Qt.DisplayRole)

                if selected_item_text:
                    # Construct the full path of the selected item
                    selected_path = os.path.join(creds.get('current_local_directory'), selected_item_text)

                    try:
                        remote_entry_path = os.path.join( creds.get('current_remote_directory'), selected_item_text )
                        # ic(remote_entry_path, selected_item_text, selected_path)

                        if os.path.isdir(selected_path):
                            # Upload a local directory to the remote server
                            self.message_signal.emit(f"Uploading directory: {selected_path}")
                            self.upload_directory(selected_path, remote_entry_path)
                        else:
                            # Upload a local file to the remote server
                            self.message_signal.emit(f"Uploading file: {selected_path}")
                            job_id = create_random_integer()
                            queue_item = QueueItem(os.path.basename(selected_path), job_id)
                            # queue_display.append(queue_item)
                            queue_display_append(queue_item)

                            # Assuming add_sftp_job handles the actual upload process
                            add_sftp_job(selected_path, False, remote_entry_path.replace("\\", "/"), True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "upload", job_id)
                    except Exception as e:
                        self.message_signal.emit(f"upload_download() {e}")
                else:
                    self.message_signal.emit("Invalid item or empty path.")
            else:
                self.message_signal.emit("No item selected or invalid index.")
        else:
            self.message_signal.emit("Current browser is not a valid QTableView.")

    def upload_directory(self, source_directory, destination_directory):
        creds = get_credentials(self.session_id)

        self.always_continue_upload = False

        try:
            remote_folder = destination_directory

            target_exists = self.sftp_exists(remote_folder)

            if target_exists and self.is_remote_directory(remote_folder) and not self.always_continue_upload:
                response = self.show_prompt_dialog(f"The folder {remote_folder} already exists. Do you want to continue uploading?", "Upload Confirmation")

                if response == QMessageBox.No:
                    # User chose not to continue
                    return
                elif response == QMessageBox.Yes:
                    # User chose to continue
                    pass  # Continue with the upload
                elif response == QMessageBox.YesToAll:
                    # User chose to always continue
                    self.always_continue_upload = True
                else:
                    # User closed the dialog
                    return
            else:
                try:
                    success = self.sftp_mkdir(remote_folder.replace("\\", "/")) 
                    if not success or self.always_continue_upload:
                        self.message_signal.emit(f"sftp_mkdir() error creating {remote_folder} but always_continue_upload is {self.always_continue_upload}")
                        return
                except Exception as e:
                    self.message_signal.emit(f"{e}")
                    pass

            local_contents = os.listdir(source_directory)

            for entry in local_contents:
                entry_path = os.path.join(source_directory, entry)
                remote_entry_path = os.path.join(remote_folder, entry)

                job_id = create_random_integer()

                if os.path.isdir(entry_path):
                    queue_item = QueueItem( os.path.basename(entry_path), job_id )
                    queue_display_append(queue_item)
                    self.sftp_mkdir(remote_entry_path.replace("\\", "/"))
                    self.upload_directory(entry_path, remote_entry_path.replace("\\", "/"))
                else:
                    self.message_signal.emit(f"{entry_path}, {remote_entry_path}")

                    queue_item = QueueItem( os.path.basename(entry_path), job_id )
                    queue_display_append(queue_item)

                    add_sftp_job(entry_path, False, remote_entry_path.replace("\\", "/"), True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "upload", job_id)

        except Exception as e:
            self.message_signal.emit(f"upload_directory() {e}")

    def show_prompt_dialog(self, text, title):
        dialog = QMessageBox(self.parent())
        dialog.setWindowTitle(title)
        dialog.setText(text)
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll)
        dialog.setDefaultButton(QMessageBox.Yes)

        return dialog.exec_()

    def sftp_exists(self, path):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        try:
            add_sftp_job(path.replace("\\", "/"), True, path.replace("\\", "/"), True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "stat", job_id )

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