Multi-threaded, multi-tabbed, ephemeral-connection based graphical SFTP cilent written in Python and Qt5


basic instructions:
type in a site ip/hostname, username, password, and optionally port in the text boxes at the top
hitting enter in the password field or port field should start a connection
in theory if you are connected to one site and do this again it will open another tab to the new additional site
right-click should give you a menu to upload/download items (if local window, upload, if remote window, download)
double clicking a remote item should either try to cd into it if its a directory or download it and prompt you for a filename/location

This was NOT auto-generated with a wizard or template -- I had actually hoped to do something like that initially, to be totally honest, but the context window limitations of the 3.5 series and 4.0 series models I used just wouldn't allow it.  
Instead, I used the LLM to craft individual functions and then manually edited them together, slowly re-working the code to have more and more similar structure and variable names, etc.
The code was then also broken up from one large source file into a properly object oriented hierarchy and distributed across several modules which made working with LLMs far easier.

In this second phase I will be trying to use tools like 'aider' and Claude/Sonnet to enhance the functionality of the existing program, and find bugs.
