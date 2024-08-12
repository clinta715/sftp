from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QListWidget, QTextEdit, QProgressBar, QSizePolicy, QScrollArea
from PyQt5.QtCore import QThreadPool, QTimer, Qt
from icecream import ic
import os

from sftp_downloadworkerclass import Transfer, DownloadWorker, sftp_queue_get, sftp_queue_isempty

MAX_TRANSFERS = 4

queue_display = []

class BackgroundThreadWindow(QMainWindow):
    def __init__(self):
        super(BackgroundThreadWindow, self).__init__()
        self.active_transfers = 0
        self.transfers = []
        self.observees = []
        self.init_ui()

    def add_observee(self,observee):
        if observee not in self.observees:
            self.observees.append(observee)
        else:
            ic("Observee already exists:", observee)

    def remove_observee(self,observee):
        if observee in self.observees:
            self.observees.remove(observee)

    def notify_observees(self):
            for observee in self.observees:
                try:
                    observee.get_files()  # Notify the observer by calling its update method
                except AttributeError as ae:
                    ic("Observee", observee, "does not implement 'get_files' method.", ae)
                except Exception as e:
                    ic("An error occurred while notifying observee", observee, e)

    def init_ui(self):
        self.layout = QVBoxLayout()

        self.list_widget = QListWidget()
        self.layout.addWidget(self.list_widget)

        self.text_console = QTextEdit()
        self.text_console.setReadOnly(True)
        self.text_console.setMaximumHeight(100)  # Limit the height of the console
        self.text_console.textChanged.connect(self.scroll_to_bottom)
        self.layout.addWidget(self.text_console)

        # Create a scroll area for transfers
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.transfer_widget = QWidget()
        self.transfer_layout = QVBoxLayout(self.transfer_widget)
        self.scroll_area.setWidget(self.transfer_widget)
        self.layout.addWidget(self.scroll_area)

        central_widget = QWidget()
        central_widget.setLayout(self.layout)
        self.setCentralWidget(central_widget)

        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(MAX_TRANSFERS)
        self.check_queue_timer = QTimer(self)
        self.check_queue_timer.timeout.connect(self.check_and_start_transfers)
        self.check_queue_timer.start(100)

    def remove_queue_item_by_id(self, id_to_remove):
        global queue_display

        # Iterate over the queue_display list and remove the item with the matching ID
        queue_display = [item for item in queue_display if item != id_to_remove]

        # Optionally, update the list widget after removal
        self.populate_queue_list()

    def populate_queue_list(self):
        global queue_display

        # Clear the list widget first
        self.list_widget.clear()

        # Iterate over the queue_display and add each filename to the list widget
        for item in queue_display:
            self.list_widget.addItem(item)

    def queue_display_append(self, item):
        global queue_display

        queue_display.append(item)

    def scroll_to_bottom(self):
        # Scroll to the bottom of the QTextEdit
        vertical_scroll_bar = self.text_console.verticalScrollBar()
        vertical_scroll_bar.setValue(vertical_scroll_bar.maximum())

    def check_and_start_transfers(self):
        while not sftp_queue_isempty() and self.active_transfers < MAX_TRANSFERS:
            job = sftp_queue_get()
            if job.command == "end":
                self._stop_flag = 1
                break
            else:
                self.start_transfer(job.id, job.source_path, job.destination_path, 
                                    job.is_source_remote, job.is_destination_remote, 
                                    job.hostname, job.port, job.username, job.password, job.command)

        self.populate_queue_list()

    def start_transfer(self, transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command):
        # Create a horizontal layout for the progress bar and cancel button
        hbox = QHBoxLayout()

        # Create the textbox
        textbox = QLineEdit()
        textbox.setReadOnly(True)  # Make it read-only if needed
        textbox.setText(os.path.basename(job_source))  # Set text if needed
        hbox.addWidget(textbox, 2)  # Add it to the layout with a stretch factor

        # Create the progress bar
        progress_bar = QProgressBar()
        hbox.addWidget(progress_bar, 3)  # Add it to the layout with a stretch factor of 3

        # Create the cancel button
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(lambda: self.transfer_finished(transfer_id))
        hbox.addWidget(cancel_button, 1)  # Add it to the layout with a stretch factor of 1

        # Add the horizontal layout to the transfer layout instead of the main layout
        self.transfer_layout.addLayout(hbox)

        # Adjust the window size if needed
        self.adjust_window_size()

        # Store references to the widgets for later use
        new_transfer = Transfer(transfer_id=transfer_id, download_worker=DownloadWorker(transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command), active=True, hbox=hbox, progress_bar=progress_bar, cancel_button=cancel_button, tbox=textbox)

        # Create and configure the download worker
        new_transfer.download_worker.signals.progress.connect(lambda tid, val: self.update_progress(tid, val))
        new_transfer.download_worker.signals.finished.connect(lambda tid: self.transfer_finished(tid))
        new_transfer.download_worker.signals.message.connect(lambda tid, msg: self.update_text_console(tid, msg))

        self.transfers.append(new_transfer)
        # Start the download worker in the thread pool
        self.thread_pool.start(new_transfer.download_worker)
        self.queue_display_append(new_transfer.download_worker.job_source)
        self.populate_queue_list()
        self.active_transfers += 1

    def transfer_finished(self, transfer_id):
        # Find the transfer
        transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)

        if transfer is None:
            self.text_console.append(f"No transfer found with ID {transfer_id}")
            return

        # Deactivate the transfer
        transfer.active = False

        # Stop the download worker if it's active
        # if transfer.download_worker and not transfer.download_worker.isFinished():
        transfer.download_worker.stop_transfer()

        if transfer.tbox:
            transfer.tbox.deleteLater()
            transfer.tbox = None

        # Remove and delete the progress bar
        if transfer.progress_bar:
            transfer.progress_bar.deleteLater()
            transfer.progress_bar = None

        # Remove and delete the cancel button
        if transfer.cancel_button:
            transfer.cancel_button.deleteLater()
            transfer.cancel_button = None

        if transfer.hbox:  # Assuming each transfer has a reference to its QHBoxLayout
            # Find the index of the layout in the main layout and remove it
            index = self.layout.indexOf(transfer.hbox)
            if index != -1:
                layout_item = self.layout.takeAt(index)
                if layout_item:
                    widget = layout_item.widget()
                    if widget:
                        widget.deleteLater()

        # Remove the transfer from the list
        self.transfers = [t for t in self.transfers if t.transfer_id != transfer_id]
        self.text_console.append("Transfer removed from the transfers list.")
        self.remove_queue_item_by_id(transfer.download_worker.job_source)
        self.populate_queue_list()
        self.active_transfers -= 1
        if transfer.download_worker.command == "upload" or transfer.download_worker.command == "download":
            self.notify_observees()

    def update_text_console(self, transfer_id, message):
        if message:
            self.text_console.append(f"{message}")

    def update_progress(self, transfer_id, value):
        # Find the transfer with the given transfer_id
        transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)

        if transfer and transfer.progress_bar:
            # Update the progress bar's value
            transfer.progress_bar.setValue(value)
        else:
            self.text_console.append(f"update_progress() No active transfer found with ID {transfer_id}")
    def adjust_window_size(self):
        # Calculate the ideal height based on the number of transfers
        ideal_height = 200 + (len(self.transfers) * 50)  # 200 for other widgets, 50 per transfer
        max_height = 600  # Set a maximum height
        new_height = min(ideal_height, max_height)
        self.resize(self.width(), new_height)
