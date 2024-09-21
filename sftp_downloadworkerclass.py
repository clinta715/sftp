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

def clear_sftp_queue():
    while True:
        try: 
            sftp_queue.get_nowait()
        except:
            break

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
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(self.hostname, self.port, self.username, self.password)
            self.sftp = self.ssh.open_sftp()
        except Exception as e:
            self.signals.message.emit(self.transfer_id,f"download_thread() {e}")
            return

        if self.is_source_remote and not self.is_destination_remote:
            # Download from remote to local
            self.signals.message.emit(self.transfer_id,f"download_thread() {self.job_source},{self.job_destination}")
            try:
                self.sftp.get(self.job_source, self.job_destination, callback=self.progress)
            except:
                self.signals.message.emit(self.transfer_id,f"Transfer {self.transfer_id} was interrupted.")

            self.signals.finished.emit(self.transfer_id)

        elif self.is_destination_remote and not self.is_source_remote :
            # Upload from local to remote
            self.signals.message.emit(self.transfer_id,f"download_thread() {self.job_source},{self.job_destination}")
            try:
                self.sftp.put(self.job_source, self.job_destination, callback=self.progress)
            except:
                self.signals.message.emit(self.transfer_id,f"Transfer {self.transfer_id} was interrupted.")

        elif self.is_source_remote and self.is_destination_remote:
            # must be a mkdir
            try:
                if self.command == "mkdir":
                    try:
                        self.sftp.mkdir(self.job_destination)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_destination)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        # ic(e)

                elif self.command == "listdir_attr":
                    try:
                        response = self.sftp.listdir_attr(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(response)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        # ic(e)

                elif self.command == "listdir":
                    try:
                        response = self.sftp.listdir(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(response)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "chdir":
                    try:
                        self.sftp.chdir(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_source)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        # ic(e)

                elif self.command == "rmdir":
                    try:
                        self.sftp.rmdir(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_source)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        # ic(e)

                elif self.command == "stat":
                    try:
                        attr = self.sftp.stat(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(attr)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        # ic(e)

                elif self.command == "remove":
                    try:
                        self.sftp.remove(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_source)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        # ic(e)

                elif self.command == "getcwd":
                    try:
                        ic("getcwd")
                        stdin, stdout, stderr = self.ssh.exec_command('cd {}'.format(self.job_source))
                        stdin, stdout, stderr = self.ssh.exec_command('pwd')
                        if stderr.read():
                            ic("Error:", stderr.read().decode())
                            pass
                        getcwd_path = stdout.read().strip().decode()
                        # .replace("\\", "/")
                        response_queues[self.transfer_id].put("success")
                        ic(getcwd_path)
                        response_queues[self.transfer_id].put(getcwd_path)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

            except Exception as e:
                self.signals.message.emit(self.transfer_id, f"{self.command} operation failed: {e}")
                response_queues[self.transfer_id].put("error")
                response_queues[self.transfer_id].put(e)

            finally:
                self.sftp.close()
                self.ssh.close()

        self.signals.finished.emit(self.transfer_id)

    def stop_transfer(self):
        self._stop_flag = True
        self.signals.message.emit(self.transfer_id, f"Transfer {self.transfer_id} ends.")
