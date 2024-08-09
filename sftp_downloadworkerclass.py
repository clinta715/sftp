from PyQt5.QtCore import QRunnable, QObject, pyqtSignal
import enum
import queue
from icecream import ic
import paramiko
import queue
import base64
import socket
import logging

# Set up logging
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

class WorkerSignals(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int)
    message = pyqtSignal(int, str)

MAX_TRANSFERS = 4

response_queues = {}
sftp_queue = queue.Queue()

class SIZE_UNIT(enum.Enum):
    BYTES = 1
    KB = 2
    MB = 3
    GB = 4

class Transfer:
    def __init__(self, transfer_id, progress_bar=None, cancel_button=None, download_worker=None, active=False, hbox=None, tbox=None ):
        self.transfer_id = transfer_id
        self.progress_bar = progress_bar
        self.cancel_button = cancel_button
        self.download_worker = download_worker
        self.active = active
        self.hbox = hbox
        self.tbox = tbox

class transferSignals(QObject):
    showhide = pyqtSignal()

class QueueItem:
    def __init__(self, name, id):
        self.name = name
        self.id = id

class SFTPJob:
    def __init__(self, source_path, is_source_remote, destination_path, is_destination_remote, hostname, username, password, port, command, id ):
        self.source_path = source_path
        self.is_source_remote = is_source_remote
        self.destination_path = destination_path
        self.is_destination_remote = is_destination_remote
        self.hostname = hostname
        self.username = username
        self.password = password
        self.port = port
        self.command = command
        self.id = id

    def to_dict(self):
        return {
            "source_path": self.source_path,
            "is_source_remote": self.is_source_remote,
            "destination_path": self.destination_path,
            "is_destination_remote": self.is_destination_remote,
            "hostname": self.hostname,
            "username": self.username,
            "password": base64.b64encode(self.password.encode()).decode(),  # Encode password
            "port": self.port,
            "command": self.command,
            "id": self.id
        }

    @staticmethod
    def from_dict(data):
        data["password"] = base64.b64decode(data["password"]).decode()  # Decode password
        return SFTPJob(**data)

def add_sftp_job(source_path, is_source_remote, destination_path, is_destination_remote, hostname, username, password, port, command, id ):
    job = SFTPJob(
        source_path, is_source_remote, destination_path, is_destination_remote,
        hostname, username, password, port, command, id )
    sftp_queue_put(job)

def sftp_queue_get():
    return(sftp_queue.get_nowait())

def sftp_queue_put(job):
    sftp_queue.put(job)

def sftp_queue_isempty():
    return sftp_queue.empty()

def sftp_queue_clear():
    sftp_queue = []

def delete_response_queue(job_id):
    if job_id in response_queues:
        del response_queues[job_id]

def create_response_queue(job_id):
    # Create a new queue
    new_queue = queue.Queue()
    # Assign the new queue to the specified job_id in response_queues
    response_queues[job_id] = new_queue
    # Return the newly created queue
    return new_queue

def check_response_queue(job_id):
    try:
        # Try to get an item from the queue without blocking
        item = response_queues[job_id].get_nowait()
        return item
    except queue.Empty:
        # If the queue is empty, return None
        return None
    
class DownloadWorker(QRunnable):
    def __init__(self, transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command=None):
        super(DownloadWorker, self).__init__()
        self.transfer_id = transfer_id
        self._stop_flag = False
        self.signals = WorkerSignals()
        self.ssh = paramiko.SSHClient()
        self.is_source_remote = is_source_remote
        self.job_source = job_source
        self.job_destination = job_destination
        self.is_destination_remote = is_destination_remote
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.command = command

    def convert_unit(self, size_in_bytes: int, unit: SIZE_UNIT):
        # """Convert the size from bytes to
        # other units like KB, MB or GB
        # """
        if unit == SIZE_UNIT.KB:
            return size_in_bytes/1024
        elif unit == SIZE_UNIT.MB:
            return size_in_bytes/(1024*1024)
        elif unit == SIZE_UNIT.GB:
            return size_in_bytes/(1024*1024*1024)
        else:
            return size_in_bytes

    def progress(self, transferred: int, tobe_transferred: int):
        # """Return progress every 50 MB"""
        if self._stop_flag:
            raise Exception("Transfer interrupted")
        percentage = round((float(transferred) / float(tobe_transferred)) * 100)
        self.signals.progress.emit(self.transfer_id,percentage)

    def run(self):
        try:
            logging.info(f"Starting transfer {self.transfer_id}")
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            if not self.hostname:
                raise ValueError("Hostname is empty")
            logging.info(f"Connecting to {self.hostname}:{self.port}")
            self.ssh.connect(self.hostname, self.port, self.username, self.password)
            self.sftp = self.ssh.open_sftp()

            if self.is_source_remote and not self.is_destination_remote:
                # Download from remote to local
                logging.info(f"Downloading {self.job_source} to {self.job_destination}")
                self.signals.message.emit(self.transfer_id, f"Downloading {self.job_source} to {self.job_destination}")
                self.sftp.get(self.job_source, self.job_destination, callback=self.progress)
            elif self.is_destination_remote and not self.is_source_remote:
                # Upload from local to remote
                logging.info(f"Uploading {self.job_source} to {self.job_destination}")
                self.signals.message.emit(self.transfer_id, f"Uploading {self.job_source} to {self.job_destination}")
                self.sftp.put(self.job_source, self.job_destination, callback=self.progress)
            elif self.is_source_remote and self.is_destination_remote:
                logging.info(f"Executing remote command for transfer {self.transfer_id}")
                self.execute_remote_command()

        except socket.gaierror as e:
            error_msg = f"Hostname resolution failed for {self.hostname}. Please check the hostname. Error: {str(e)}"
            logging.error(error_msg)
            self.signals.message.emit(self.transfer_id, error_msg)
        except ValueError as ve:
            error_msg = f"Invalid hostname: {str(ve)}"
            logging.error(error_msg)
            self.signals.message.emit(self.transfer_id, error_msg)
        except paramiko.AuthenticationException:
            error_msg = "Authentication failed. Please check your credentials."
            logging.error(error_msg)
            self.signals.message.emit(self.transfer_id, error_msg)
        except paramiko.SSHException as ssh_exception:
            error_msg = f"SSH connection failed: {str(ssh_exception)}"
            logging.error(error_msg)
            self.signals.message.emit(self.transfer_id, error_msg)
        except IOError as io_error:
            error_msg = f"I/O error: {str(io_error)}"
            logging.error(error_msg)
            self.signals.message.emit(self.transfer_id, error_msg)
        except OSError as os_error:
            error_msg = f"OS error: {str(os_error)}"
            logging.error(error_msg)
            self.signals.message.emit(self.transfer_id, error_msg)
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logging.error(error_msg)
            self.signals.message.emit(self.transfer_id, error_msg)
        finally:
            if hasattr(self, 'sftp'):
                self.sftp.close()
            if hasattr(self, 'ssh'):
                self.ssh.close()
            logging.info(f"Transfer {self.transfer_id} finished")
            self.signals.finished.emit(self.transfer_id)

    def execute_remote_command(self):
        try:
            if self.command == "mkdir":
                self.sftp.mkdir(self.job_destination)
                self.put_response("success", self.job_destination)
            elif self.command == "listdir_attr":
                response = self.sftp.listdir_attr(self.job_source)
                self.put_response("success", response)
            elif self.command == "listdir":
                response = self.sftp.listdir(self.job_source)
                self.put_response("success", response)
            elif self.command == "chdir":
                self.sftp.chdir(self.job_source)
                self.put_response("success", self.job_source)
            elif self.command == "rmdir":
                self.sftp.rmdir(self.job_source)
                self.put_response("success", self.job_source)
            elif self.command == "stat":
                attr = self.sftp.stat(self.job_source)
                self.put_response("success", attr)
            elif self.command == "remove":
                self.sftp.remove(self.job_source)
                self.put_response("success", self.job_source)
            elif self.command == "getcwd":
                stdin, stdout, stderr = self.ssh.exec_command(f'cd {self.job_source} && pwd')
                if stderr.read():
                    ic("Error:", stderr.read().decode())
                getcwd_path = stdout.read().strip().decode()
                self.put_response("success", getcwd_path)
            elif self.command == "close":
                self.put_response("success", "SFTP connection closed")
            else:
                raise ValueError(f"Unknown command: {self.command}")
        except Exception as e:
            self.signals.message.emit(self.transfer_id, f"{self.command} operation failed: {str(e)}")
            self.put_response("error", str(e))

    def put_response(self, status, data):
        response_queues[self.transfer_id].put(status)
        response_queues[self.transfer_id].put(data)

    def stop_transfer(self):
        self._stop_flag = True
        self.signals.message.emit(self.transfer_id, f"Transfer {self.transfer_id} ends.")
from PyQt5.QtCore import QRunnable, QObject, pyqtSignal
import enum
import queue
from icecream import ic
import paramiko
import queue
import base64

class WorkerSignals(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int)
    message = pyqtSignal(int, str)

MAX_TRANSFERS = 4

response_queues = {}
sftp_queue = queue.Queue()

class SIZE_UNIT(enum.Enum):
    BYTES = 1
    KB = 2
    MB = 3
    GB = 4

class Transfer:
    def __init__(self, transfer_id, progress_bar=None, cancel_button=None, download_worker=None, active=False, hbox=None, tbox=None ):
        self.transfer_id = transfer_id
        self.progress_bar = progress_bar
        self.cancel_button = cancel_button
        self.download_worker = download_worker
        self.active = active
        self.hbox = hbox
        self.tbox = tbox

class transferSignals(QObject):
    showhide = pyqtSignal()

class QueueItem:
    def __init__(self, name, id):
        self.name = name
        self.id = id

class SFTPJob:
    def __init__(self, source_path, is_source_remote, destination_path, is_destination_remote, hostname, username, password, port, command, id ):
        self.source_path = source_path
        self.is_source_remote = is_source_remote
        self.destination_path = destination_path
        self.is_destination_remote = is_destination_remote
        self.hostname = hostname
        self.username = username
        self.password = password
        self.port = port
        self.command = command
        self.id = id

    def to_dict(self):
        return {
            "source_path": self.source_path,
            "is_source_remote": self.is_source_remote,
            "destination_path": self.destination_path,
            "is_destination_remote": self.is_destination_remote,
            "hostname": self.hostname,
            "username": self.username,
            "password": base64.b64encode(self.password.encode()).decode(),  # Encode password
            "port": self.port,
            "command": self.command,
            "id": self.id
        }

    @staticmethod
    def from_dict(data):
        data["password"] = base64.b64decode(data["password"]).decode()  # Decode password
        return SFTPJob(**data)

def add_sftp_job(source_path, is_source_remote, destination_path, is_destination_remote, hostname, username, password, port, command, id ):
    job = SFTPJob(
        source_path, is_source_remote, destination_path, is_destination_remote,
        hostname, username, password, port, command, id )
    sftp_queue_put(job)

def sftp_queue_get():
    return(sftp_queue.get_nowait())

def sftp_queue_put(job):
    sftp_queue.put(job)

def sftp_queue_isempty():
    return sftp_queue.empty()

def sftp_queue_clear():
    sftp_queue = []

def delete_response_queue(job_id):
    if job_id in response_queues:
        del response_queues[job_id]

def create_response_queue(job_id):
    # Create a new queue
    new_queue = queue.Queue()
    # Assign the new queue to the specified job_id in response_queues
    response_queues[job_id] = new_queue
    # Return the newly created queue
    return new_queue

def check_response_queue(job_id):
    try:
        # Try to get an item from the queue without blocking
        item = response_queues[job_id].get_nowait()
        return item
    except queue.Empty:
        # If the queue is empty, return None
        return None
    
class DownloadWorker(QRunnable):
    def __init__(self, transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command=None):
        super(DownloadWorker, self).__init__()
        self.transfer_id = transfer_id
        self._stop_flag = False
        self.signals = WorkerSignals()
        self.ssh = paramiko.SSHClient()
        self.is_source_remote = is_source_remote
        self.job_source = job_source
        self.job_destination = job_destination
        self.is_destination_remote = is_destination_remote
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.command = command

    def convert_unit(self, size_in_bytes: int, unit: SIZE_UNIT):
        if unit == SIZE_UNIT.KB:
            return size_in_bytes/1024
        elif unit == SIZE_UNIT.MB:
            return size_in_bytes/(1024*1024)
        elif unit == SIZE_UNIT.GB:
            return size_in_bytes/(1024*1024*1024)
        else:
            return size_in_bytes

    def progress(self, transferred: int, tobe_transferred: int):
        if self._stop_flag:
            raise Exception("Transfer interrupted")
        percentage = round((float(transferred) / float(tobe_transferred)) * 100)
        self.signals.progress.emit(self.transfer_id, percentage)

    def run(self):
        try:
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(self.hostname, self.port, self.username, self.password)
            self.sftp = self.ssh.open_sftp()
        except socket.gaierror as e:
            error_msg = f"Hostname resolution failed for {self.hostname}. Please check the hostname. Error: {str(e)}"
            self.signals.message.emit(self.transfer_id, error_msg)
            return
        except paramiko.AuthenticationException:
            error_msg = "Authentication failed. Please check your credentials."
            self.signals.message.emit(self.transfer_id, error_msg)
            return
        except paramiko.SSHException as ssh_exception:
            error_msg = f"SSH connection failed: {str(ssh_exception)}"
            self.signals.message.emit(self.transfer_id, error_msg)
            return
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.signals.message.emit(self.transfer_id, error_msg)
            return

        try:
            if self.is_source_remote and not self.is_destination_remote:
                # Download from remote to local
                self.signals.message.emit(self.transfer_id, f"Downloading {self.job_source} to {self.job_destination}")
                self.sftp.get(self.job_source, self.job_destination, callback=self.progress)
            elif self.is_destination_remote and not self.is_source_remote:
                # Upload from local to remote
                self.signals.message.emit(self.transfer_id, f"Uploading {self.job_source} to {self.job_destination}")
                self.sftp.put(self.job_source, self.job_destination, callback=self.progress)
            elif self.is_source_remote and self.is_destination_remote:
                self.execute_remote_command()
        except IOError as io_error:
            self.signals.message.emit(self.transfer_id, f"I/O error: {str(io_error)}")
        except OSError as os_error:
            self.signals.message.emit(self.transfer_id, f"OS error: {str(os_error)}")
        except Exception as e:
            self.signals.message.emit(self.transfer_id, f"Transfer {self.transfer_id} was interrupted: {str(e)}")
        finally:
            if hasattr(self, 'sftp'):
                self.sftp.close()
            if hasattr(self, 'ssh'):
                self.ssh.close()
            self.signals.finished.emit(self.transfer_id)

    def execute_remote_command(self):
        try:
            if self.command == "mkdir":
                self.sftp.mkdir(self.job_destination)
                self.put_response("success", self.job_destination)
            elif self.command == "listdir_attr":
                response = self.sftp.listdir_attr(self.job_source)
                self.put_response("success", response)
            elif self.command == "listdir":
                response = self.sftp.listdir(self.job_source)
                self.put_response("success", response)
            elif self.command == "chdir":
                self.sftp.chdir(self.job_source)
                self.put_response("success", self.job_source)
            elif self.command == "rmdir":
                self.sftp.rmdir(self.job_source)
                self.put_response("success", self.job_source)
            elif self.command == "stat":
                attr = self.sftp.stat(self.job_source)
                self.put_response("success", attr)
            elif self.command == "remove":
                self.sftp.remove(self.job_source)
                self.put_response("success", self.job_source)
            elif self.command == "getcwd":
                stdin, stdout, stderr = self.ssh.exec_command(f'cd {self.job_source} && pwd')
                if stderr.read():
                    self.signals.message.emit(self.transfer_id, f"Error: {stderr.read().decode()}")
                getcwd_path = stdout.read().strip().decode()
                self.put_response("success", getcwd_path)
            elif self.command == "close":
                self.put_response("success", "SFTP connection closed")
            else:
                raise ValueError(f"Unknown command: {self.command}")
        except Exception as e:
            self.signals.message.emit(self.transfer_id, f"{self.command} operation failed: {str(e)}")
            self.put_response("error", str(e))

    def put_response(self, status, data):
        response_queues[self.transfer_id].put(status)
        response_queues[self.transfer_id].put(data)

    def stop_transfer(self):
        self._stop_flag = True
        self.signals.message.emit(self.transfer_id, f"Transfer {self.transfer_id} ends.")
