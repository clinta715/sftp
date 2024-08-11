Multi-threaded, multi-tabbed, ephemeral-connection based graphical SFTP cilent written in Python and Qt5


Basic Instructions:
type in a site ip/hostname, username, password, and optionally port in the text boxes at the top
hitting enter in the password field or port field should start a connection
in theory if you are connected to one site and do this again it will open another tab to the new additional site
right-click should give you a menu to upload/download items (if local window, upload, if remote window, download)
double clicking a remote item should either try to cd into it if its a directory or download it and prompt you for a filename/location

This was NOT auto-generated with a wizard or template -- I had actually hoped to do something like that initially, to be totally honest, but the context window limitations of the 3.5 series and 4.0 series models I used just wouldn't allow it.  
Instead, I used the LLM to craft individual functions and then manually edited them together, slowly re-working the code to have more and more similar structure and variable names, etc.
The code was then also broken up from one large source file into a properly object oriented hierarchy and distributed across several modules which made working with LLMs far easier.

In this second phase I will be trying to use tools like 'aider' and Claude/Sonnet to enhance the functionality of the existing program, and find bugs.

Internal Structure:
Internally, the program maintains an array of all the current site connections and their associated credentials.  
All the various 'tabs' for different sites send their commands to a background thread that connects to the corresponding site, executes the commands, and closes the connection.
Periodically commands are issued like 'pwd' and ssh 'cd' to determine the remote working directory which is stored with the site/tab/credential information (all of which is used by the background command execution thread to coordinate where files are uploaded, where we end up when the user clicks '..', or clicks into a subdirectory, etc)
Clicking on a remote subdirectory, for example, checks to see if that directory exists and is a valid path, and then closes the connection and sets the current_remote_path variable for that site.  Because there is only one 'local' site, we just use a local getcwd() to determine that location and store it whenever it changes.
All the commands like cd, get, put, ls, etc, are pushed onto a stack that is then pop'd by the background thread and executed and the responses are placed in a corresponding response queue.
These queues are created on the fly by generating a random number, checking it hasn't been used already, and then assigning this number as an 'id' to the queue.  Once the sequence is completed the queue is deleted.

Design Afterthoughts:
One issue, to me, is that I had planned to make a much more elaborate and 'cool' looking GUI.  I unfortunately did too good of a job of classing and subclassing everything such that it's very tedious for all the classes like the left, right browser and the various transfer queue window(s) and text output windows to communicate with each other.  Were I to do it again I would put everything in the main window GUI into one class by itself (and use QT Creator from the start instead of Notepad++)
However, one of the goals of the project was to re-familiarize myself with proper OOP hierarchical design and I think this is a good example of that.
